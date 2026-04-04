import json
import os
from datetime import datetime

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import func
from sqlmodel import Session, select

import ml_client
from database import get_db
from models import Contract, SteItem, UserEvent

router = APIRouter()

_TEMPLATES_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "frontend", "templates")
templates = Jinja2Templates(directory=_TEMPLATES_DIR)


@router.get("/", response_class=HTMLResponse)
async def page_home(request: Request, inn: str = "", db: Session = Depends(get_db)):
    recommended = []
    suggested_query = None
    is_personalized = False
    contracts_count = 0

    if inn:
        contracts = db.exec(
            select(Contract)
            .where(Contract.inn == inn)
            .order_by(Contract.contract_date.desc())  # type: ignore[arg-type]
            .limit(20)
        ).all()
        ste_ids = list({c.ste_id for c in contracts})
        if ste_ids:
            recommended = db.exec(
                select(SteItem).where(SteItem.ste_id.in_(ste_ids)).limit(12)  # type: ignore[attr-defined]
            ).all()
            is_personalized = True
            contracts_count = len(contracts)
        suggested_query = await ml_client.get_suggestion(inn)

    if not recommended:
        recommended = db.exec(select(SteItem).limit(12)).all()

    rec_ste_ids = [item.ste_id for item in recommended]
    price_rows = db.exec(
        select(Contract.ste_id, func.min(Contract.contract_sum))
        .where(
            Contract.ste_id.in_(rec_ste_ids),  # type: ignore[attr-defined]
            Contract.contract_sum.is_not(None),  # type: ignore[union-attr]
        )
        .group_by(Contract.ste_id)
    ).all()
    rec_prices = {row[0]: f"от {int(row[1]):,} ₽".replace(",", "\u00a0") for row in price_rows}

    return templates.TemplateResponse(request, "index.html", {
        "inn": inn,
        "recommended": recommended,
        "rec_prices": rec_prices,
        "suggested_query": suggested_query,
        "is_personalized": is_personalized,
        "contracts_count": contracts_count,
    })


@router.get("/search", response_class=HTMLResponse)
async def page_search(
    request: Request,
    q: str = "",
    inn: str = "",
    sort: str = "relevance",
    page: int = 1,
    db: Session = Depends(get_db),
):
    results = []
    total = 0
    suggested_query = None
    is_personalized = False
    page_size = 12

    if q:
        candidates_orm = db.exec(
            select(SteItem).where(SteItem.name.ilike(f"%{q}%"))  # type: ignore[union-attr]
        ).all()
        candidates = [
            {"ste_id": s.ste_id, "name": s.name, "category": s.category, "bm25_score": 1.0}
            for s in candidates_orm
        ]

        if inn and candidates:
            history_orm = db.exec(
                select(UserEvent)
                .where(UserEvent.inn == inn)
                .order_by(UserEvent.created_at.desc())  # type: ignore[arg-type]
                .limit(50)
            ).all()
            history = [
                {"ste_id": e.ste_id, "event_type": e.event_type, "dwell_ms": e.dwell_ms}
                for e in history_orm
            ]
            ml_response = await ml_client.get_ranked_results(q, inn, candidates, history)
            if ml_response and ml_response.get("results"):
                results = ml_response["results"]
                suggested_query = ml_response.get("suggested_query")
                is_personalized = True
            else:
                results = candidates
        else:
            results = candidates

        # Обогатить значками
        if inn:
            purchased_ids = {
                row[0]
                for row in db.exec(select(Contract.ste_id).where(Contract.inn == inn)).all()
            }
            for item in results:
                item["badges"] = []
                if item["ste_id"] in purchased_ids:
                    item["badges"].append("frequent")
                if item.get("score", 0) > 0.8:
                    item["badges"].append("ai")

        total = len(results)

        if sort == "relevance":
            results.sort(key=lambda x: x.get("score", 0), reverse=True)

        offset = (page - 1) * page_size
        results = results[offset : offset + page_size]

        # Лучшая цена для каждой позиции на текущей странице — один запрос
        page_ste_ids = [r["ste_id"] for r in results]
        if page_ste_ids:
            price_rows = db.exec(
                select(Contract.ste_id, func.min(Contract.contract_sum))
                .where(
                    Contract.ste_id.in_(page_ste_ids),  # type: ignore[attr-defined]
                    Contract.contract_sum.is_not(None),  # type: ignore[union-attr]
                )
                .group_by(Contract.ste_id)
            ).all()
            price_map = {row[0]: row[1] for row in price_rows}
            for item in results:
                price = price_map.get(item["ste_id"])
                item["best_price"] = f"от {int(price):,} ₽".replace(",", "\u00a0") if price else None

    total_pages = max(1, (total + page_size - 1) // page_size)

    return templates.TemplateResponse(request, "search.html", {
        "query": q,
        "inn": inn,
        "sort": sort,
        "results": results,
        "total": total,
        "page": page,
        "total_pages": total_pages,
        "suggested_query": suggested_query,
        "is_personalized": is_personalized,
    })


@router.get("/card/{ste_id}", response_class=HTMLResponse)
async def page_card(
    request: Request,
    ste_id: str,
    inn: str = "",
    query: str = "",
    position: int = 1,
    db: Session = Depends(get_db),
):
    ste = db.exec(select(SteItem).where(SteItem.ste_id == ste_id)).first()
    if not ste:
        return HTMLResponse("Товар не найден", status_code=404)

    # Парсинг атрибутов: сначала пробуем JSON, затем "ключ:значение;..." формат CSV
    attributes: list[str] = []
    if ste.attributes:
        try:
            parsed = json.loads(ste.attributes)
            if isinstance(parsed, list):
                attributes = [str(a) for a in parsed]
            elif isinstance(parsed, dict):
                attributes = [f"{k}: {v}" for k, v in list(parsed.items())[:8]]
            else:
                raise ValueError
        except Exception:
            attributes = [a.strip() for a in ste.attributes.split(";") if ":" in a.strip()][:8]

    purchase_history = []
    explain = None
    total_purchases = 0
    total_sum = 0.0
    badges: list[str] = []

    if inn:
        contracts = db.exec(
            select(Contract)
            .where(Contract.ste_id == ste_id, Contract.inn == inn)
            .order_by(Contract.contract_date.desc())  # type: ignore[arg-type]
            .limit(10)
        ).all()

        purchase_history = [
            {
                "date": c.contract_date.strftime("%d.%m.%Y") if c.contract_date else "—",
                "supplier": c.supplier_name or "—",
                "sum": f"{int(c.contract_sum):,} ₽".replace(",", " ") if c.contract_sum else "—",
            }
            for c in contracts
        ]
        total_purchases = len(contracts)
        total_sum = sum(c.contract_sum or 0.0 for c in contracts)

        if purchase_history:
            badges.append("frequent")

            all_contracts_count = db.exec(
                select(Contract).where(Contract.inn == inn)
            ).all()
            freq = min(100, int(len(contracts) / max(len(all_contracts_count), 1) * 1000))

            last_date = contracts[0].contract_date if contracts else None
            days_ago = (datetime.utcnow() - last_date).days if last_date else 999
            recency = max(0, 100 - days_ago // 3)

            explain = {
                "reasons": [
                    {"label": "Частота закупок", "value": freq},
                    {"label": "Давность последней закупки", "value": recency},
                    {"label": "Популярность среди схожих организаций", "value": 25},
                ]
            }

    total_sum_fmt = f"{int(total_sum):,} ₽".replace(",", "\u00a0") if total_sum else "0 ₽"

    # Рыночные предложения: все контракты по этой СТЕ, лучшая цена по каждому поставщику
    market_contracts = db.exec(
        select(Contract)
        .where(
            Contract.ste_id == ste_id,
            Contract.contract_sum.is_not(None),  # type: ignore[union-attr]
        )
        .order_by(Contract.contract_sum.asc())  # type: ignore[arg-type]
        .limit(100)
    ).all()

    seen_suppliers: set[str] = set()
    offers: list[dict] = []
    for c in market_contracts:
        key = c.supplier_inn or c.supplier_name or c.inn
        if not key or key in seen_suppliers:
            continue
        seen_suppliers.add(key)
        offers.append({
            "supplier": c.supplier_name or c.supplier_inn or "—",
            "sum": c.contract_sum,
            "sum_fmt": f"{int(c.contract_sum):,} ₽".replace(",", "\u00a0"),  # type: ignore[arg-type]
            "date": c.contract_date.strftime("%d.%m.%Y") if c.contract_date else "—",
        })
        if len(offers) >= 5:
            break

    best_offer = offers[0] if offers else None

    return templates.TemplateResponse(request, "card.html", {
        "ste": ste,
        "attributes": attributes,
        "inn": inn,
        "query": query,
        "position": position,
        "purchase_history": purchase_history,
        "explain": explain,
        "total_purchases": total_purchases,
        "total_sum": total_sum_fmt,
        "badges": badges,
        "offers": offers,
        "best_offer": best_offer,
    })
