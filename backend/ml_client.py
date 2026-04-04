import logging
import os
from typing import Any

import httpx

logger = logging.getLogger(__name__)

ML_SERVICE_URL = os.getenv("ML_SERVICE_URL", "http://ml_service:8001")
_HTTP_TIMEOUT = 2.0


async def get_ranked_results(
    query: str,
    inn: str,
    candidates: list[dict[str, Any]],
    history: list[dict[str, Any]],
) -> dict[str, Any]:
    try:
        async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT) as client:
            response = await client.post(
                f"{ML_SERVICE_URL}/rank",
                json={"query": query, "inn": inn, "candidates": candidates, "history": history},
            )
            response.raise_for_status()
            return response.json()
    except Exception as exc:
        logger.warning("ML /rank failed (%s), using fallback", exc)
        return _fallback_results(candidates)


async def send_event(inn: str, ste_id: str, event_type: str, dwell_ms: int | None) -> None:
    try:
        async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT) as client:
            await client.post(
                f"{ML_SERVICE_URL}/event",
                json={"inn": inn, "ste_id": ste_id, "event_type": event_type, "dwell_ms": dwell_ms},
            )
    except Exception as exc:
        logger.warning("ML /event failed for inn=%s: %s", inn, exc)


async def get_suggestion(inn: str) -> str | None:
    try:
        async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT) as client:
            response = await client.get(f"{ML_SERVICE_URL}/suggest", params={"inn": inn})
            response.raise_for_status()
            return response.json().get("suggested_query")
    except Exception as exc:
        logger.warning("ML /suggest failed for inn=%s: %s", inn, exc)
        return None


def _fallback_results(candidates: list[dict[str, Any]]) -> dict[str, Any]:
    results = [
        {
            "ste_id": c["ste_id"],
            "score": 0.0,
            "reason": "fallback: ML-сервис недоступен",
        }
        for c in candidates
    ]
    return {"results": results, "suggested_query": None}
