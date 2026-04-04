import json
import time
from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlmodel import Session, select

import ml_client
from database import get_db
from models import Contract, SearchLog, SteItem, UserEvent

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


def _build_history(inn: str, session: Session) -> dict[str, Any]:
    contracts = session.exec(
        select(Contract).where(Contract.inn == inn).limit(100)
    ).all()
    events = session.exec(
        select(UserEvent).where(UserEvent.inn == inn).limit(200)
    ).all()
    return {
        "contracts": [
            {"ste_id": c.ste_id, "purchase_name": c.purchase_name}
            for c in contracts
        ],
        "events": [
            {"ste_id": e.ste_id, "event_type": e.event_type, "query": e.query}
            for e in events
        ],
    }


@router.post("/search", response_model=SearchResponse)
async def search(body: SearchRequest, session: Session = Depends(get_db)):
    t0 = time.monotonic()

    history = _build_history(body.inn, session)
    ml_response = await ml_client.get_ranked_results(body.query, body.inn, history)

    latency_ms = int((time.monotonic() - t0) * 1000)
    result_ids = [r["ste_id"] for r in ml_response.get("results", [])]

    log = SearchLog(
        inn=body.inn,
        query=body.query,
        result_ids=json.dumps(result_ids),
        latency_ms=latency_ms,
    )
    session.add(log)
    session.commit()

    results = [SteResult(**r) for r in ml_response.get("results", [])]
    return SearchResponse(
        results=results,
        suggested_query=ml_response.get("suggested_query"),
    )
