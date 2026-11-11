"""Per-user watchlists. Every query is scoped to the signed-in user."""

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from ..db import get_db
from ..deps import get_current_user
from ..models import Security, User, Watchlist, WatchlistItem
from ..schemas import ORM, SecurityOut

router = APIRouter(prefix="/api/watchlists", tags=["watchlists"])


class ItemOut(ORM):
    id: int
    note: str
    added_at: datetime
    security: SecurityOut


class WatchlistOut(ORM):
    id: int
    name: str
    created_at: datetime
    items: list[ItemOut]


class WatchlistIn(BaseModel):
    name: str = Field(min_length=1, max_length=80)


class ItemIn(BaseModel):
    ticker: str = Field(min_length=1, max_length=20)
    note: str = Field("", max_length=2000)


class ItemUpdate(BaseModel):
    note: str = Field("", max_length=2000)


def owned_watchlist(db: Session, user: User, watchlist_id: int) -> Watchlist:
    wl = db.scalar(select(Watchlist).where(Watchlist.id == watchlist_id, Watchlist.user_id == user.id))
    if wl is None:
        raise HTTPException(404, "Watchlist not found")
    return wl


@router.get("", response_model=list[WatchlistOut])
def list_watchlists(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return db.scalars(
        select(Watchlist)
        .where(Watchlist.user_id == user.id)
        .options(selectinload(Watchlist.items).selectinload(WatchlistItem.security))
        .order_by(Watchlist.created_at)
    ).all()


@router.post("", response_model=WatchlistOut, status_code=201)
def create_watchlist(data: WatchlistIn, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    wl = Watchlist(user_id=user.id, name=data.name.strip())
    db.add(wl)
    db.commit()
    return wl


@router.patch("/{watchlist_id}", response_model=WatchlistOut)
def rename_watchlist(
    watchlist_id: int, data: WatchlistIn, db: Session = Depends(get_db), user: User = Depends(get_current_user)
):
    wl = owned_watchlist(db, user, watchlist_id)
    wl.name = data.name.strip()
    db.commit()
    return wl


@router.delete("/{watchlist_id}", status_code=204)
def delete_watchlist(watchlist_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    db.delete(owned_watchlist(db, user, watchlist_id))
    db.commit()


@router.post("/{watchlist_id}/items", response_model=ItemOut, status_code=201)
def add_item(
    watchlist_id: int, data: ItemIn, db: Session = Depends(get_db), user: User = Depends(get_current_user)
):
    wl = owned_watchlist(db, user, watchlist_id)
    sec = db.scalar(select(Security).where(Security.ticker == data.ticker.strip().upper()))
    if sec is None:
        raise HTTPException(404, "Unknown ticker. Only securities from the synced reference list can be added.")
    item = WatchlistItem(watchlist_id=wl.id, security_id=sec.id, note=data.note)
    db.add(item)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, f"{sec.ticker} is already in this watchlist")
    db.refresh(item)
    return item


@router.patch("/{watchlist_id}/items/{item_id}", response_model=ItemOut)
def update_item(
    watchlist_id: int,
    item_id: int,
    data: ItemUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    wl = owned_watchlist(db, user, watchlist_id)
    item = db.scalar(select(WatchlistItem).where(WatchlistItem.id == item_id, WatchlistItem.watchlist_id == wl.id))
    if item is None:
        raise HTTPException(404, "Item not found")
    item.note = data.note
    db.commit()
    return item


@router.delete("/{watchlist_id}/items/{item_id}", status_code=204)
def remove_item(
    watchlist_id: int, item_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)
):
    wl = owned_watchlist(db, user, watchlist_id)
    item = db.scalar(select(WatchlistItem).where(WatchlistItem.id == item_id, WatchlistItem.watchlist_id == wl.id))
    if item is None:
        raise HTTPException(404, "Item not found")
    db.delete(item)
    db.commit()
