"""Shared response models."""

from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict


class ORM(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class UserOut(ORM):
    id: int
    username: str
    display_name: str
    role: str
    created_at: datetime


class SecurityOut(ORM):
    id: int
    ticker: str
    name: str
    cik: int | None
    exchange: str | None
    source: str
    is_listed: bool
    updated_at: datetime


class QuoteOut(BaseModel):
    """Latest stored end-of-day close. Never real-time."""

    close: Decimal
    date: date
    prev_close: Decimal | None
    prev_date: date | None
    change: Decimal | None
    change_pct: Decimal | None
    source: str
    currency: str
