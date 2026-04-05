import logging
import os
from typing import Any

import httpx

logger = logging.getLogger(__name__)

ML_SERVICE_URL = os.getenv("ML_SERVICE_URL", "http://ml_service:8000")
_HTTP_TIMEOUT = 5.0


async def search(query: str, inn: str, top_n: int = 100) -> dict[str, Any] | None:
    """
    GET /search — BM25 + LightGBM ранжирование.
    Возвращает dict с ключами results, corrected, was_corrected, synonyms_used и др.
    Каждый элемент results содержит ste_id (int), ml_score, why_tags, bundle, price_analogues.
    """
    try:
        params: dict[str, Any] = {"q": query, "top_n": top_n}
        if inn:
            params["inn"] = inn
        async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT) as client:
            response = await client.get(f"{ML_SERVICE_URL}/search", params=params)
            response.raise_for_status()
            return response.json()
    except Exception as exc:
        logger.warning("ML /search failed (%s), using DB fallback", exc)
        return None


async def send_event(inn: str, ste_id: str, event_type: str, dwell_ms: int | None) -> None:
    """POST /event — логирует поведение пользователя в Redis-сессию ML-сервиса."""
    try:
        async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT) as client:
            await client.post(
                f"{ML_SERVICE_URL}/event",
                json={
                    "user_inn":   inn,
                    "ste_id":     int(ste_id) if ste_id else 0,
                    "event_type": event_type,
                    "dwell_ms":   dwell_ms or 0,
                },
            )
    except Exception as exc:
        logger.warning("ML /event failed for inn=%s: %s", inn, exc)


async def suggest(query: str, inn: str) -> dict[str, Any] | None:
    """
    GET /suggest — AI-предсказание запроса в реальном времени.
    Возвращает {"suggestions": [...], "ai_recommended_query": str|null}.
    """
    if len(query.strip()) < 3:
        return None
    try:
        params: dict[str, Any] = {"q": query}
        if inn:
            params["inn"] = inn
        async with httpx.AsyncClient(timeout=2.0) as client:
            response = await client.get(f"{ML_SERVICE_URL}/suggest", params=params)
            response.raise_for_status()
            return response.json()
    except Exception as exc:
        logger.warning("ML /suggest failed for q=%r inn=%s: %s", query, inn, exc)
        return None


async def get_analogues(ste_id: str) -> list[dict[str, Any]]:
    """GET /analogues/{ste_id} — ценовые аналоги из ML-индекса."""
    try:
        async with httpx.AsyncClient(timeout=2.0) as client:
            response = await client.get(f"{ML_SERVICE_URL}/analogues/{ste_id}")
            response.raise_for_status()
            return response.json().get("analogues") or []
    except Exception as exc:
        logger.warning("ML /analogues failed for ste_id=%s: %s", ste_id, exc)
        return []


# ── Обратная совместимость с вызовами из pages.py ────────────────────────────

async def get_ranked_results(
    query: str,
    inn: str,
    candidates: list[dict[str, Any]],
    history: list[dict[str, Any]],
) -> dict[str, Any] | None:
    """Устаревший интерфейс — делегирует к search()."""
    return await search(query, inn, top_n=100)


async def get_suggestion(inn: str) -> str | None:
    """Устаревший интерфейс — возвращает только ai_recommended_query."""
    return None
