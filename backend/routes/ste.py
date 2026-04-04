import json
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlmodel import Session, select

from database import get_db
from models import SteItem

router = APIRouter()


class SteResponse(BaseModel):
    ste_id: str
    name: str
    category: str | None
    attributes: dict[str, Any] | None


@router.get("/ste/{ste_id}", response_model=SteResponse)
def get_ste(ste_id: str, session: Session = Depends(get_db)):
    item = session.exec(select(SteItem).where(SteItem.ste_id == ste_id)).first()
    if item is None:
        raise HTTPException(status_code=404, detail="СТЕ не найдена")

    attributes = None
    if item.attributes:
        try:
            attributes = json.loads(item.attributes)
        except (json.JSONDecodeError, TypeError):
            attributes = {"raw": item.attributes}

    return SteResponse(
        ste_id=item.ste_id,
        name=item.name,
        category=item.category,
        attributes=attributes,
    )
