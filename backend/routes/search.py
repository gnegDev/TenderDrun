import json
import time
from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlmodel import Session, select

import ml_client
from database import get_db
from models import SearchLog, SteItem, UserEvent

router = APIRouter()


class SearchRequest(BaseModel):
    query: str
    inn: str


class SteResult(BaseModel):
    ste_id: str
    name: str
    category: str | None
    score: float
    reason: str


class SearchResponse(BaseModel):
    results: list[SteResult]
    suggested_query: str | None


def _get_candidates(query: str, session: Session) -> list[dict[str, Any]]:
    """BM25-заглушка: простой ILIKE-поиск, вернуть до 20 кандидатов."""
    items = session.exec(
        select(SteItem).where(SteItem.name.ilike(f"%{query}%")).limit(20)  # type: ignore[union-attr]
    ).all()
    return [
        {"ste_id": item.ste_id, "name": item.name, "category": item.category, "bm25_score": 1.0}
        for item in items
    ]


def _get_history(inn: str, session: Session) -> list[dict[str, Any]]:
    events = session.exec(
        select(UserEvent)
        .where(UserEvent.inn == inn)
        .order_by(UserEvent.created_at.desc())  # type: ignore[arg-type]
        .limit(50)
    ).all()
    return [
        {"ste_id": e.ste_id, "event_type": e.event_type, "dwell_ms": e.dwell_ms}
        for e in events
    ]


def _enrich(ml_results: list[dict], ste_map: dict[str, SteItem]) -> list[SteResult]:
    """Дополнить ответ ML именем и категорией из таблицы ste."""
    enriched = []
    for r in ml_results:
        item = ste_map.get(r["ste_id"])
        enriched.append(SteResult(
            ste_id=r["ste_id"],
            name=item.name if item else r["ste_id"],
            category=item.category if item else None,
            score=r.get("score", 0.0),
            reason=r.get("reason", ""),
        ))
    return enriched


@router.post("/search", response_model=SearchResponse)
async def search(body: SearchRequest, session: Session = Depends(get_db)):
    t0 = time.monotonic()

    candidates = _get_candidates(body.query, session)
    history = _get_history(body.inn, session)

    ml_response = await ml_client.get_ranked_results(body.query, body.inn, candidates, history)

    latency_ms = int((time.monotonic() - t0) * 1000)
    ml_results = ml_response.get("results", [])
    result_ids = [r["ste_id"] for r in ml_results]

    # Загрузить данные ste для обогащения одним запросом
    ste_items = session.exec(select(SteItem).where(SteItem.ste_id.in_(result_ids))).all()  # type: ignore[attr-defined]
    ste_map = {item.ste_id: item for item in ste_items}

    log = SearchLog(
        inn=body.inn,
        query=body.query,
        result_ids=json.dumps(result_ids),
        latency_ms=latency_ms,
    )
    session.add(log)
    session.commit()

    return SearchResponse(
        results=_enrich(ml_results, ste_map),
        suggested_query=ml_response.get("suggested_query"),
    )
