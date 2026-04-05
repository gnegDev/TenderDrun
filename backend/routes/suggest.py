from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlmodel import Session, select

import ml_client
from database import get_db
from models import UserEvent

router = APIRouter()


class SuggestResponse(BaseModel):
    suggested_query: str | None


class InfluenceEntry(BaseModel):
    ste_id: str
    event_type: str
    influence: str


class ExplainResponse(BaseModel):
    reasons: list[InfluenceEntry]


_INFLUENCE_LABELS = {
    "click": "пользователь кликнул на позицию",
    "dwell": "пользователь долго изучал позицию",
    "quick_return": "пользователь быстро вернулся — позиция не подошла",
    "target_action": "пользователь совершил целевое действие",
    "impression_skip": "пользователь проигнорировал позицию",
}


@router.get("/suggest", response_model=SuggestResponse)
async def suggest(inn: str):
    suggested_query = await ml_client.get_suggestion(inn)
    return SuggestResponse(suggested_query=suggested_query)


@router.get("/api/autocomplete")
async def autocomplete(q: str = Query(default=""), inn: str = Query(default="")):
    """
    Автодополнение поисковой строки — топ-6 подсказок.
    Вызывается при каждом нажатии клавиши (debounce 150 мс на клиенте).
    Учитывает опечатки (SymSpell), синонимы и поведение пользователя в сессии.
    """
    if len(q.strip()) < 2:
        return {"suggestions": []}
    result = await ml_client.suggest(q.strip(), inn)
    if not result:
        return {"suggestions": []}
    suggestions = (result.get("suggestions") or [])[:6]
    return {"suggestions": suggestions}


@router.get("/explain", response_model=ExplainResponse)
def explain(inn: str, query: str, session: Session = Depends(get_db)):
    events = session.exec(
        select(UserEvent)
        .where(UserEvent.inn == inn)
        .order_by(UserEvent.created_at.desc())  # type: ignore[arg-type]
        .limit(20)
    ).all()

    reasons = [
        InfluenceEntry(
            ste_id=e.ste_id,
            event_type=e.event_type,
            influence=_INFLUENCE_LABELS.get(e.event_type, e.event_type),
        )
        for e in events
    ]
    return ExplainResponse(reasons=reasons)
