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
    category: str = "",
    price_from: str = "",
    price_to: str = "",
    has_offers: str = "",
    db: Session = Depends(get_db),
):
    results: list[dict] = []
    total = 0
    suggested_query = None
    is_personalized = False
    page_size = 12
    _has_offers = has_offers in ("true", "on", "1", "yes")
    _price_from = float(price_from.strip()) if price_from.strip() else None
    _price_to = float(price_to.strip()) if price_to.strip() else None

    if q:
        # Подзапрос лучшей цены — используется в обоих путях (ML и fallback)
        price_subq = (
            select(Contract.ste_id, func.min(Contract.contract_sum).label("min_price"))
            .where(Contract.contract_sum.is_not(None))  # type: ignore[union-attr]
            .group_by(Contract.ste_id)
            .subquery()
        )

        price_map: dict[str, float] = {}

        # ── Путь 1: ML-сервис (BM25 + LightGBM) ─────────────────────────────
        ml_response = await ml_client.search(q, inn, top_n=200)

        # Скорректированный запрос из ML — используем в DB-поиске даже при fallback
        ml_corrected_q = (
            ml_response.get("corrected") if ml_response and ml_response.get("was_corrected") else None
        )

        if ml_response:
            ml_results = ml_response.get("results") or []
            suggested_query = ml_corrected_q
            is_personalized = bool(inn) and bool(ml_results)

            # ML отдаёт ste_id как int; в DB он хранится строкой
            ml_ids = [str(r["ste_id"]) for r in ml_results]

            # Применяем фильтры из DB на кандидатах ML
            ste_query = (
                select(SteItem, price_subq.c.min_price)
                .outerjoin(price_subq, SteItem.ste_id == price_subq.c.ste_id)
                .where(SteItem.ste_id.in_(ml_ids))  # type: ignore[attr-defined]
            )
            if category:
                ste_query = ste_query.where(SteItem.category.ilike(f"%{category}%"))  # type: ignore[union-attr]
            if _has_offers:
                ste_query = ste_query.where(price_subq.c.min_price.is_not(None))
            if _price_from is not None:
                ste_query = ste_query.where(price_subq.c.min_price >= _price_from)
            if _price_to is not None:
                ste_query = ste_query.where(price_subq.c.min_price <= _price_to)

            rows = db.exec(ste_query).all()

            valid_ids: set[str] = set()
            for row in rows:
                item, min_price = row[0], row[1]
                valid_ids.add(item.ste_id)
                if min_price is not None:
                    price_map[item.ste_id] = min_price

            # Сохраняем ML-порядок, убираем позиции, не прошедшие DB-фильтры
            for r in ml_results:
                sid = str(r["ste_id"])
                if sid not in valid_ids:
                    continue
                results.append({
                    "ste_id":    sid,
                    "name":      r.get("name", ""),
                    "category":  r.get("category", ""),
                    "ml_score":  r.get("ml_score", 0.0),
                    "why_tags":  r.get("why_tags") or [],
                    "badges":    [],
                })

            if sort == "price_asc":
                results.sort(key=lambda x: price_map.get(x["ste_id"], float("inf")))

        # ── Путь 2: DB ILIKE — ML недоступен или вернул 0 совпадений с DB ────
        if not results:
            effective_q = ml_corrected_q or q

            def _ilike_search(search_q: str) -> list:
                """Запускает ILIKE-поиск по search_q с применением текущих фильтров."""
                sq = (
                    select(SteItem, price_subq.c.min_price)
                    .outerjoin(price_subq, SteItem.ste_id == price_subq.c.ste_id)
                    .where(SteItem.name.ilike(f"%{search_q}%"))  # type: ignore[union-attr]
                )
                if category:
                    sq = sq.where(SteItem.category.ilike(f"%{category}%"))  # type: ignore[union-attr]
                if _has_offers:
                    sq = sq.where(price_subq.c.min_price.is_not(None))
                if _price_from is not None:
                    sq = sq.where(price_subq.c.min_price >= _price_from)
                if _price_to is not None:
                    sq = sq.where(price_subq.c.min_price <= _price_to)
                if sort == "price_asc":
                    sq = sq.order_by(price_subq.c.min_price.asc().nulls_last())
                rows_ = db.exec(sq).all()
                out = []
                for row_ in rows_:
                    item_, min_price_ = row_[0], row_[1]
                    if min_price_ is not None:
                        price_map[item_.ste_id] = min_price_
                    out.append({
                        "ste_id":   item_.ste_id,
                        "name":     item_.name,
                        "category": item_.category,
                        "why_tags": [],
                        "badges":   [],
                    })
                return out

            # Попытка 1: точный запрос (или скорректированный ML-ом)
            results = _ilike_search(effective_q)

            # Попытка 2: prefix-поиск по первым 3+ символам (спасает от опечаток
            # когда ML недоступен и ILIKE на опечатке даёт 0).
            # "флэг" → "флэ%" → найдёт "флэш", "флэшка" и пр.
            if not results and not category and len(effective_q.strip()) >= 3:
                prefix = effective_q.strip()[:3]
                results = _ilike_search(prefix)

        # ── Значки «Часто покупаете» из DB ───────────────────────────────────
        if inn and results:
            purchased_ids = {
                row[0]
                for row in db.exec(select(Contract.ste_id).where(Contract.inn == inn)).all()
            }
            for item in results:
                if item["ste_id"] in purchased_ids and "frequent" not in item["badges"]:
                    item["badges"].append("frequent")

        total = len(results)
        offset = (page - 1) * page_size
        results = results[offset : offset + page_size]

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
        "category": category,
        "price_from": price_from,
        "price_to": price_to,
        "has_offers": _has_offers,
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

    # ML-аналоги: похожие позиции дешевле (из обученного индекса)
    # Пересчитываем savings_pct относительно актуальной лучшей цены из БД,
    # а не медианы из обучающих данных ML — они могут расходиться.
    ml_analogues_raw = await ml_client.get_analogues(ste_id)
    reference_price = best_offer["sum"] if best_offer else None
    ml_analogues: list[dict] = []
    for a in (ml_analogues_raw or []):
        analogue_price = a.get("median_price")
        if not analogue_price or analogue_price <= 0:
            continue
        if reference_price:
            if analogue_price >= reference_price:
                # Аналог не дешевле реальной лучшей цены — пропускаем
                continue
            savings = round((reference_price - analogue_price) / reference_price * 100, 1)
        else:
            # Нет реальных контрактов по текущей позиции — оставляем как есть
            savings = a.get("savings_pct") or 0
        ml_analogues.append({**a, "savings_pct": savings})
    ml_analogues.sort(key=lambda x: x["savings_pct"], reverse=True)

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
        "ml_analogues": ml_analogues,
    })
