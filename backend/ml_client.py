import logging
import os
from typing import Any

import httpx
from sqlmodel import Session, select

from database import engine
from models import SteItem

logger = logging.getLogger(__name__)

ML_SERVICE_URL = os.getenv("ML_SERVICE_URL", "http://ml_service:8001")
_HTTP_TIMEOUT = 5.0


async def get_ranked_results(query: str, inn: str, history: dict[str, Any]) -> dict[str, Any]:
    try:
        async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT) as client:
            response = await client.post(
                f"{ML_SERVICE_URL}/rank",
                json={"query": query, "inn": inn, "history": history},
            )
            response.raise_for_status()
            return response.json()
    except Exception as exc:
        logger.warning("ML /rank failed (%s), using fallback", exc)
        return _fallback_results()


async def reindex(inn: str) -> None:
    try:
        async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT) as client:
            await client.post(f"{ML_SERVICE_URL}/reindex", json={"inn": inn})
    except Exception as exc:
        logger.warning("ML /reindex failed for inn=%s: %s", inn, exc)


async def get_suggestion(inn: str) -> str | None:
    try:
        async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT) as client:
            response = await client.get(f"{ML_SERVICE_URL}/suggest", params={"inn": inn})
            response.raise_for_status()
            data = response.json()
            return data.get("suggested_query")
    except Exception as exc:
        logger.warning("ML /suggest failed for inn=%s: %s", inn, exc)
        return None


def _fallback_results() -> dict[str, Any]:
    with Session(engine) as session:
        items = session.exec(select(SteItem).limit(10)).all()
    results = [
        {
            "ste_id": item.ste_id,
            "name": item.name,
            "category": item.category,
            "score": 0.0,
            "reason": "fallback: ML-сервис недоступен",
        }
        for item in items
    ]
    return {"results": results, "suggested_query": None}
