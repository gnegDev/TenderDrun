import asyncio
import os

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel
from sqlmodel import Session, func, select

import ml_client
from database import get_db
from models import CartItem, SteItem

router = APIRouter()

_TEMPLATES_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "frontend", "templates")
templates = Jinja2Templates(directory=_TEMPLATES_DIR)


class CartAddRequest(BaseModel):
    inn: str
    ste_id: str


# ── HTML-страница корзины ─────────────────────────────────────────────────────

@router.get("/cart", response_class=HTMLResponse)
async def page_cart(request: Request, inn: str = "", db: Session = Depends(get_db)):
    items: list[CartItem] = []
    if inn:
        items = db.exec(
            select(CartItem)
            .where(CartItem.inn == inn)
            .order_by(CartItem.added_at.desc())  # type: ignore[arg-type]
        ).all()
    return templates.TemplateResponse(request, "cart.html", {
        "inn": inn,
        "items": items,
    })


# ── JSON API ──────────────────────────────────────────────────────────────────

@router.get("/api/cart")
def get_cart(inn: str = "", db: Session = Depends(get_db)):
    """Возвращает содержимое корзины и количество позиций."""
    if not inn:
        return {"items": [], "count": 0}
    items = db.exec(select(CartItem).where(CartItem.inn == inn)).all()
    return {
        "items": [
            {"ste_id": i.ste_id, "name": i.ste_name, "category": i.ste_category}
            for i in items
        ],
        "count": len(items),
    }


@router.post("/api/cart")
async def add_to_cart(body: CartAddRequest, db: Session = Depends(get_db)):
    """Добавляет товар в корзину. При повторном добавлении возвращает already_in_cart."""
    if not body.inn or not body.ste_id:
        return {"status": "error", "message": "inn и ste_id обязательны"}

    existing = db.exec(
        select(CartItem).where(
            CartItem.inn == body.inn,
            CartItem.ste_id == body.ste_id,
        )
    ).first()
    if existing:
        return {"status": "already_in_cart", "count": _count(body.inn, db)}

    ste = db.exec(select(SteItem).where(SteItem.ste_id == body.ste_id)).first()

    db.add(CartItem(
        inn=body.inn,
        ste_id=body.ste_id,
        ste_name=ste.name if ste else body.ste_id,
        ste_category=ste.category if ste else None,
    ))
    db.commit()

    # Отправляем сигнал «purchase» в ML — сильнейший буст (+0.50) для последующих поисков
    asyncio.create_task(ml_client.send_event(body.inn, body.ste_id, "purchase", 0))

    return {"status": "added", "count": _count(body.inn, db)}


@router.delete("/api/cart/{ste_id}")
def remove_from_cart(ste_id: str, inn: str = "", db: Session = Depends(get_db)):
    """Удаляет товар из корзины."""
    item = db.exec(
        select(CartItem).where(
            CartItem.inn == inn,
            CartItem.ste_id == ste_id,
        )
    ).first()
    if item:
        db.delete(item)
        db.commit()
    return {"status": "removed", "count": _count(inn, db)}


def _count(inn: str, db: Session) -> int:
    result = db.exec(
        select(func.count(CartItem.id)).where(CartItem.inn == inn)  # type: ignore[arg-type]
    ).first()
    return result or 0
