from datetime import datetime
from typing import Optional

from sqlmodel import Field, SQLModel


class SteItem(SQLModel, table=True):
    __tablename__ = "ste"

    id: Optional[int] = Field(default=None, primary_key=True)
    ste_id: str = Field(index=True, unique=True)
    name: str
    category: Optional[str] = None
    attributes: Optional[str] = None  # JSON-строка


class Contract(SQLModel, table=True):
    __tablename__ = "contracts"

    id: Optional[int] = Field(default=None, primary_key=True)
    contract_id: str = Field(index=True)
    ste_id: str = Field(index=True)
    inn: str = Field(index=True)
    customer_name: Optional[str] = None
    supplier_inn: Optional[str] = None
    supplier_name: Optional[str] = None
    purchase_name: Optional[str] = None
    contract_date: Optional[datetime] = None
    contract_sum: Optional[float] = None


class UserEvent(SQLModel, table=True):
    __tablename__ = "user_events"

    id: Optional[int] = Field(default=None, primary_key=True)
    inn: str = Field(index=True)
    query: str
    ste_id: str
    position: int
    event_type: str  # click | dwell | quick_return | target_action | impression_skip
    dwell_ms: Optional[int] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)


class CartItem(SQLModel, table=True):
    __tablename__ = "cart_items"

    id: Optional[int] = Field(default=None, primary_key=True)
    inn: str = Field(index=True)
    ste_id: str = Field(index=True)
    ste_name: str = ""
    ste_category: Optional[str] = None
    added_at: datetime = Field(default_factory=datetime.utcnow)


class SearchLog(SQLModel, table=True):
    __tablename__ = "search_logs"

    id: Optional[int] = Field(default=None, primary_key=True)
    inn: str = Field(index=True)
    query: str
    result_ids: str  # JSON-список ste_id
    latency_ms: Optional[int] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
