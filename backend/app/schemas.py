"""Shared response models."""

from datetime import datetime

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
