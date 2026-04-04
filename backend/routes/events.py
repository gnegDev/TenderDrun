import asyncio

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlmodel import Session

import ml_client
from database import get_db
from models import UserEvent

router = APIRouter()


class EventRequest(BaseModel):
    inn: str
    query: str
    ste_id: str
    position: int
    event_type: str
    dwell_ms: int | None = None


@router.post("/event")
async def record_event(body: EventRequest, session: Session = Depends(get_db)):
    event = UserEvent(
        inn=body.inn,
        query=body.query,
        ste_id=body.ste_id,
        position=body.position,
        event_type=body.event_type,
        dwell_ms=body.dwell_ms,
    )
    session.add(event)
    session.commit()

    asyncio.create_task(ml_client.send_event(body.inn, body.ste_id, body.event_type, body.dwell_ms))

    return {"status": "ok"}
