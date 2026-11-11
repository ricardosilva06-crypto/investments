"""Security reference data (SEC EDGAR list) and global search."""

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import case, func, or_, select
from sqlalchemy.orm import Session

from ..db import get_db
from ..deps import get_current_user
from ..models import DataSync, Note, Portfolio, Security, Transaction, User, Watchlist, WatchlistItem
from ..schemas import SecurityOut
from ..services import sec

router = APIRouter(prefix="/api", tags=["securities"])


def _escape_like(term: str) -> str:
    return term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _filters(q: str, exchange: str | None) -> list:
    conds = [Security.is_listed.is_(True)]
    if exchange:
        conds.append(Security.exchange == exchange)
    if q:
        up, low = _escape_like(q.upper()), _escape_like(q.lower())
        conds.append(
            or_(
                Security.ticker.like(f"{up}%", escape="\\"),
                func.lower(Security.name).like(f"%{low}%", escape="\\"),
                Security.cik == (int(q) if q.isdigit() else -1),
            )
        )
    return conds


def search_securities(db: Session, q: str, limit: int = 20, exchange: str | None = None, offset: int = 0):
    q = q.strip()
    stmt = select(Security).where(*_filters(q, exchange))
    if q:
        up, low = _escape_like(q.upper()), _escape_like(q.lower())
        rank = case(
            (Security.ticker == q.upper(), 0),
            (Security.ticker.like(f"{up}%", escape="\\"), 1),
            (func.lower(Security.name).like(f"{low}%", escape="\\"), 2),
            else_=3,
        )
        stmt = stmt.order_by(rank, func.length(Security.ticker), Security.ticker)
    else:
        stmt = stmt.order_by(Security.name)
    return db.scalars(stmt.offset(offset).limit(limit)).all()


def count_securities(db: Session, q: str, exchange: str | None = None) -> int:
    return db.scalar(select(func.count()).select_from(Security).where(*_filters(q.strip(), exchange))) or 0


class ExchangeCount(BaseModel):
    exchange: str
    count: int


class SecuritiesPage(BaseModel):
    items: list[SecurityOut]
    total: int
    source: str
    source_url: str
    last_success_at: str | None


@router.get("/securities", response_model=SecuritiesPage)
def list_securities(
    q: str = Query("", max_length=80),
    exchange: str | None = Query(None, max_length=32),
    limit: int = Query(30, ge=1, le=100),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    items = search_securities(db, q, limit=limit, exchange=exchange, offset=offset)
    total = count_securities(db, q, exchange)
    sync = db.get(DataSync, sec.SOURCE)
    return SecuritiesPage(
        items=items,
        total=total,
        source="SEC EDGAR company_tickers_exchange.json",
        source_url=sec.SOURCE_URL,
        last_success_at=sync.last_success_at.isoformat() if sync and sync.last_success_at else None,
    )


@router.get("/securities/exchanges", response_model=list[ExchangeCount])
def exchanges(db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    rows = db.execute(
        select(Security.exchange, func.count())
        .where(Security.is_listed.is_(True), Security.exchange.is_not(None))
        .group_by(Security.exchange)
        .order_by(func.count().desc())
    ).all()
    return [ExchangeCount(exchange=e, count=c) for e, c in rows]


class SecurityDetail(BaseModel):
    security: SecurityOut
    edgar_url: str | None
    watchlist_ids: list[int]
    note_count: int


@router.get("/securities/{ticker}", response_model=SecurityDetail)
def get_security(ticker: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    s = db.scalar(select(Security).where(Security.ticker == ticker.upper()))
    if s is None:
        raise HTTPException(404, "Security not found")
    wl_ids = db.scalars(
        select(WatchlistItem.watchlist_id)
        .join(Watchlist)
        .where(Watchlist.user_id == user.id, WatchlistItem.security_id == s.id)
    ).all()
    notes = db.scalar(select(func.count()).select_from(Note).where(Note.user_id == user.id, Note.security_id == s.id))
    edgar = (
        f"https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK={s.cik:010d}&type=&dateb=&owner=include&count=40"
        if s.cik
        else None
    )
    return SecurityDetail(security=s, edgar_url=edgar, watchlist_ids=list(wl_ids), note_count=notes or 0)


class SearchHit(BaseModel):
    type: str  # security | note | watchlist | holding
    title: str
    subtitle: str
    href: str


@router.get("/search", response_model=list[SearchHit])
def global_search(
    q: str = Query(..., min_length=1, max_length=80),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    hits: list[SearchHit] = []
    term = f"%{_escape_like(q.strip().lower())}%"

    for w in db.scalars(
        select(Watchlist).where(Watchlist.user_id == user.id, func.lower(Watchlist.name).like(term, escape="\\")).limit(3)
    ):
        hits.append(SearchHit(type="watchlist", title=w.name, subtitle="Watchlist", href=f"/watchlist?id={w.id}"))

    symbols = db.execute(
        select(Transaction.symbol, Portfolio.id, Portfolio.name)
        .join(Portfolio)
        .where(Portfolio.user_id == user.id, func.lower(Transaction.symbol).like(term, escape="\\"))
        .distinct()
        .limit(5)
    ).all()
    for sym, pid, pname in symbols:
        hits.append(SearchHit(type="holding", title=sym, subtitle=f"In portfolio · {pname}", href=f"/portfolio?id={pid}"))

    for n in db.scalars(
        select(Note)
        .where(
            Note.user_id == user.id,
            or_(func.lower(Note.title).like(term, escape="\\"), func.lower(Note.body).like(term, escape="\\")),
        )
        .order_by(Note.updated_at.desc())
        .limit(5)
    ):
        hits.append(SearchHit(type="note", title=n.title, subtitle="Note", href=f"/notes?id={n.id}"))

    for s in search_securities(db, q, limit=15):
        hits.append(
            SearchHit(
                type="security",
                title=s.ticker,
                subtitle=f"{s.name}{' · ' + s.exchange if s.exchange else ''}",
                href=f"/company?t={s.ticker}",
            )
        )
    return hits
