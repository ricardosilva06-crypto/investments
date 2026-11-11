"""Notifications, preferences, dashboard, system status and data export."""

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session, selectinload

from ..db import get_db, utcnow
from ..deps import get_current_user
from ..models import ChatMessage, Conversation, DataSync, Document, Note, Notification, Portfolio, Security, User, UserPreference, Watchlist, WatchlistItem
from ..schemas import ORM, QuoteOut, SecurityOut
from ..services.prices import latest_quotes
from ..services import ai
from ..services.portfolio import LedgerError, build_ledger

router = APIRouter(prefix="/api", tags=["account"])


# ---------------------------------------------------------------- notifications
class NotificationOut(ORM):
    id: int
    kind: str
    title: str
    body: str
    link: str
    created_at: datetime
    read_at: datetime | None


@router.get("/notifications", response_model=list[NotificationOut])
def list_notifications(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return db.scalars(
        select(Notification).where(Notification.user_id == user.id).order_by(Notification.created_at.desc()).limit(100)
    ).all()


@router.post("/notifications/{nid}/read", status_code=204)
def mark_read(nid: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    n = db.scalar(select(Notification).where(Notification.id == nid, Notification.user_id == user.id))
    if n is None:
        raise HTTPException(404, "Notification not found")
    n.read_at = n.read_at or utcnow()
    db.commit()


@router.post("/notifications/read-all", status_code=204)
def mark_all_read(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    db.execute(
        update(Notification)
        .where(Notification.user_id == user.id, Notification.read_at.is_(None))
        .values(read_at=utcnow())
    )
    db.commit()


# ---------------------------------------------------------------- preferences
class PreferencesIO(ORM):
    theme: str = Field(pattern="^(dark|light|system)$")
    base_currency: str = Field(min_length=3, max_length=3, pattern="^[A-Z]{3}$")
    compact_numbers: bool


def _prefs(db: Session, user: User) -> UserPreference:
    p = db.get(UserPreference, user.id)
    if p is None:
        p = UserPreference(user_id=user.id)
        db.add(p)
        db.commit()
    return p


@router.get("/preferences", response_model=PreferencesIO)
def get_prefs(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return _prefs(db, user)


@router.put("/preferences", response_model=PreferencesIO)
def put_prefs(data: PreferencesIO, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    p = _prefs(db, user)
    p.theme, p.base_currency, p.compact_numbers = data.theme, data.base_currency, data.compact_numbers
    db.commit()
    return p


# ---------------------------------------------------------------- system status
class SourceStatus(ORM):
    source: str
    source_url: str
    status: str
    message: str
    record_count: int
    last_attempt_at: datetime | None
    last_success_at: datetime | None


class AIStatus(BaseModel):
    available: bool
    url: str
    models: list[str]
    message: str


class SystemStatus(BaseModel):
    server_time: datetime
    data_sources: list[SourceStatus]
    ai: AIStatus


@router.get("/system/status", response_model=SystemStatus)
def system_status(db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    return SystemStatus(
        server_time=utcnow(),
        data_sources=db.scalars(select(DataSync).order_by(DataSync.source)).all(),
        ai=AIStatus(**ai.ollama_status()),
    )


# ---------------------------------------------------------------- dashboard
class DashWatchItem(BaseModel):
    watchlist_id: int
    watchlist_name: str
    security: SecurityOut
    note: str
    quote: QuoteOut | None = None


class DashNote(ORM):
    id: int
    title: str
    updated_at: datetime


class DashPortfolio(BaseModel):
    id: int
    name: str
    open_positions: int
    cost_basis_by_currency: dict[str, str]
    error: str | None = None


class Dashboard(BaseModel):
    display_name: str
    watchlist_count: int
    watched_securities: int
    watch_items: list[DashWatchItem]
    recent_notes: list[DashNote]
    note_count: int
    portfolios: list[DashPortfolio]
    unread_notifications: int
    securities_available: int
    data_sources: list[SourceStatus]


@router.get("/dashboard", response_model=Dashboard)
def dashboard(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    wls = db.scalars(
        select(Watchlist)
        .where(Watchlist.user_id == user.id)
        .options(selectinload(Watchlist.items).selectinload(WatchlistItem.security))
        .order_by(Watchlist.created_at)
    ).all()
    items = [
        DashWatchItem(watchlist_id=w.id, watchlist_name=w.name, security=i.security, note=i.note)
        for w in wls
        for i in w.items
    ]
    items.sort(key=lambda x: x.security.ticker)
    quotes = latest_quotes(db, sorted({i.security.ticker for i in items}))
    for i in items:
        q = quotes.get(i.security.ticker)
        i.quote = QuoteOut(**q) if q else None
    portfolios = []
    for p in db.scalars(
        select(Portfolio).where(Portfolio.user_id == user.id).options(selectinload(Portfolio.transactions))
    ):
        try:
            ledger = build_ledger(list(p.transactions))
            open_pos = [x for x in ledger.positions.values() if x.quantity > 0]
            by_ccy: dict[str, object] = {}
            for x in open_pos:
                by_ccy[x.currency] = by_ccy.get(x.currency, 0) + x.cost_basis
            portfolios.append(
                DashPortfolio(
                    id=p.id,
                    name=p.name,
                    open_positions=len(open_pos),
                    cost_basis_by_currency={k: format(v, "f") for k, v in by_ccy.items()},
                )
            )
        except LedgerError as exc:
            portfolios.append(DashPortfolio(id=p.id, name=p.name, open_positions=0, cost_basis_by_currency={}, error=str(exc)))
    return Dashboard(
        display_name=user.display_name,
        watchlist_count=len(wls),
        watched_securities=len({i.security.id for i in items}),
        watch_items=items[:12],
        recent_notes=db.scalars(
            select(Note).where(Note.user_id == user.id).order_by(Note.updated_at.desc()).limit(5)
        ).all(),
        note_count=db.scalar(select(func.count()).select_from(Note).where(Note.user_id == user.id)) or 0,
        portfolios=portfolios,
        unread_notifications=db.scalar(
            select(func.count())
            .select_from(Notification)
            .where(Notification.user_id == user.id, Notification.read_at.is_(None))
        )
        or 0,
        securities_available=db.scalar(select(func.count()).select_from(Security).where(Security.is_listed.is_(True)))
        or 0,
        data_sources=db.scalars(select(DataSync).order_by(DataSync.source)).all(),
    )


# ---------------------------------------------------------------- export
@router.get("/me/export")
def export_my_data(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """Everything this user owns, as JSON. Never includes other users' data."""

    def tx(t):
        return {
            "symbol": t.symbol, "kind": t.kind, "trade_date": t.trade_date.isoformat(),
            "quantity": format(t.quantity, "f"), "price": format(t.price, "f"), "fees": format(t.fees, "f"),
            "currency": t.currency, "note": t.note,
        }

    prefs = db.get(UserPreference, user.id)
    payload = {
        "exported_at": utcnow().isoformat(),
        "format": "investor-intelligence-user-export/1",
        "user": {"username": user.username, "display_name": user.display_name, "created_at": user.created_at.isoformat()},
        "preferences": {"theme": prefs.theme, "base_currency": prefs.base_currency} if prefs else None,
        "watchlists": [
            {"name": w.name, "items": [{"ticker": i.security.ticker, "note": i.note, "added_at": i.added_at.isoformat()} for i in w.items]}
            for w in db.scalars(select(Watchlist).where(Watchlist.user_id == user.id))
        ],
        "portfolios": [
            {"name": p.name, "transactions": [tx(t) for t in p.transactions]}
            for p in db.scalars(select(Portfolio).where(Portfolio.user_id == user.id))
        ],
        "notes": [
            {"title": n.title, "body": n.body, "ticker": n.security.ticker if n.security else None,
             "created_at": n.created_at.isoformat(), "updated_at": n.updated_at.isoformat()}
            for n in db.scalars(select(Note).where(Note.user_id == user.id))
        ],
        "ai_conversations": [
            {"title": c.title, "created_at": c.created_at.isoformat(), "messages": [
                {"role": m.role, "task": m.task, "content": m.content, "model": m.model, "tickers": m.tickers,
                 "created_at": m.created_at.isoformat()}
                for m in db.scalars(select(ChatMessage).where(ChatMessage.conversation_id == c.id).order_by(ChatMessage.id))
            ]}
            for c in db.scalars(select(Conversation).where(Conversation.user_id == user.id))
        ],
        "documents": [
            {"title": d.title, "filename": d.filename, "pages": d.pages, "sha256": d.sha256, "uploaded_at": d.created_at.isoformat(),
             "note": "PDF files are not embedded; download them from the Documents page."}
            for d in db.scalars(select(Document).where(Document.user_id == user.id))
        ],
    }
    stamp = utcnow().strftime("%Y%m%d")
    return JSONResponse(
        payload, headers={"Content-Disposition": f'attachment; filename="investor-intelligence-{user.username}-{stamp}.json"'}
    )
