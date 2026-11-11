"""Phase 5: news, alerts, push subscriptions, background jobs, security check."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field, field_validator, model_validator
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..config import get_settings
from ..db import get_db
from ..deps import get_current_user, require_admin
from ..models import (Alert, Filing, Feed, JobRun, NewsItem, PushSubscription, Security, User, Watchlist,
                      WatchlistItem)
from ..schemas import ORM
from ..services import alerts as alertsvc
from ..services import news, push, scheduler

router = APIRouter(prefix="/api", tags=["engage"])


# ------------------------------------------------------------------ news
class FeedIn(BaseModel):
    url: str = Field(min_length=8, max_length=500)
    title: str = Field("", max_length=160)
    ticker: str | None = Field(None, max_length=20)

    @field_validator("url")
    @classmethod
    def _url(cls, v: str) -> str:
        v = v.strip()
        if not v.startswith(("https://", "http://")):
            raise ValueError("Feed URL must start with https:// or http://")
        return v


class FeedOut(ORM):
    id: int
    url: str
    title: str
    ticker: str | None
    status: str
    message: str
    last_fetch_at: datetime | None


@router.get("/feeds", response_model=list[FeedOut])
def list_feeds(db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    return db.scalars(select(Feed).order_by(Feed.title)).all()


@router.get("/feeds/suggested")
def suggested_feeds(_: User = Depends(require_admin)):
    return news.SUGGESTED


@router.post("/admin/feeds", response_model=FeedOut, status_code=201)
def add_feed(data: FeedIn, db: Session = Depends(get_db), _: User = Depends(require_admin)):
    if db.scalar(select(Feed).where(Feed.url == data.url)):
        raise HTTPException(409, "This feed is already added")
    ticker = data.ticker.strip().upper() if data.ticker and data.ticker.strip() else None
    if ticker and not db.scalar(select(Security).where(Security.ticker == ticker)):
        raise HTTPException(404, "Unknown ticker")
    f = Feed(url=data.url, title=data.title.strip() or data.url, ticker=ticker)
    db.add(f)
    db.commit()
    news.fetch(db, f, force=True)
    if f.status == "error":
        msg = f.message
        db.delete(f)
        db.commit()
        raise HTTPException(422, f"Could not read this feed: {msg}")
    db.refresh(f)
    return f


@router.delete("/admin/feeds/{feed_id}", status_code=204)
def delete_feed(feed_id: int, db: Session = Depends(get_db), _: User = Depends(require_admin)):
    f = db.get(Feed, feed_id)
    if f is None:
        raise HTTPException(404, "Feed not found")
    db.delete(f)
    db.commit()


@router.post("/admin/feeds/refresh")
def refresh_feeds(db: Session = Depends(get_db), _: User = Depends(require_admin)):
    n = sum(news.fetch(db, f, force=True) for f in db.scalars(select(Feed)).all())
    return {"new_items": n}


def _my_tickers(db: Session, user: User) -> set[str]:
    t = set(db.scalars(select(Security.ticker).join(WatchlistItem, WatchlistItem.security_id == Security.id)
                       .join(Watchlist).where(Watchlist.user_id == user.id)))
    from ..models import Portfolio, Transaction

    t |= set(db.scalars(select(Transaction.symbol).join(Portfolio).where(Portfolio.user_id == user.id)))
    return t


@router.get("/news")
def get_news(
    scope: str = Query("all", pattern="^(all|mine)$"),
    feed_id: int | None = None,
    limit: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Headlines from feeds, plus recent SEC filings of the user's companies (scope=mine)."""
    items: list[dict] = []
    stmt = select(NewsItem, Feed).join(Feed)
    mine = _my_tickers(db, user) if scope == "mine" else set()
    if feed_id:
        stmt = stmt.where(NewsItem.feed_id == feed_id)
    if scope == "mine":
        stmt = stmt.where(Feed.ticker.in_(mine)) if mine else stmt.where(False)
    for n, f in db.execute(stmt.order_by(func.coalesce(NewsItem.published_at, NewsItem.fetched_at).desc()).limit(limit)):
        items.append({"type": "news", "title": n.title, "link": n.link, "summary": n.summary, "source": f.title,
                      "ticker": f.ticker, "date": (n.published_at or n.fetched_at).isoformat(), "date_is_published": n.published_at is not None})
    if scope == "mine" and mine and not feed_id:
        secs = {s.cik: s.ticker for s in db.scalars(select(Security).where(Security.ticker.in_(mine), Security.cik.is_not(None)))}
        if secs:
            from ..services.fundamentals import filing_url

            for fl in db.scalars(select(Filing).where(Filing.cik.in_(secs), Filing.form.in_(("10-K", "10-Q", "8-K", "20-F", "6-K", "DEF 14A", "S-1")))
                                 .order_by(Filing.filing_date.desc()).limit(limit)):
                items.append({"type": "filing", "title": f"{secs[fl.cik]} filed {fl.form}" + (f": {fl.description}" if fl.description and fl.description != fl.form else ""),
                              "link": filing_url(fl.cik, fl.accession, fl.primary_document), "summary": "", "source": "SEC EDGAR",
                              "ticker": secs[fl.cik], "date": fl.filing_date.isoformat(), "date_is_published": True})
    items.sort(key=lambda i: i["date"], reverse=True)
    return {"items": items[:limit], "tracked_tickers": sorted(mine),
            "note": "Headlines and links only; articles open on the publisher's site. SEC filings come from stored company data (refreshed daily for tracked companies)."}


# ------------------------------------------------------------------ alerts
class AlertIn(BaseModel):
    ticker: str = Field(min_length=1, max_length=20)
    kind: str
    threshold: Decimal | None = None
    forms: str = Field("", max_length=80)
    repeat: bool = False
    note: str = Field("", max_length=200)

    @model_validator(mode="after")
    def _check(self):
        if self.kind not in alertsvc.KINDS:
            raise ValueError("Unknown alert type")
        if self.kind != "filing":
            if self.threshold is None or not self.threshold.is_finite() or self.threshold <= 0:
                raise ValueError("Enter a positive threshold")
            if self.kind == "daily_move" and self.threshold > 1:
                raise ValueError("Daily move is a fraction (0.05 = 5%)")
        return self


class AlertOut(ORM):
    id: int
    ticker: str
    kind: str
    threshold: Decimal | None
    forms: str
    active: bool
    repeat: bool
    note: str
    last_checked_at: datetime | None
    last_triggered_at: datetime | None
    created_at: datetime


@router.get("/alerts", response_model=list[AlertOut])
def list_alerts(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return db.scalars(select(Alert).where(Alert.user_id == user.id).order_by(Alert.active.desc(), Alert.created_at.desc())).all()


@router.post("/alerts", response_model=AlertOut, status_code=201)
def create_alert(data: AlertIn, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    t = data.ticker.strip().upper()
    if not db.scalar(select(Security).where(Security.ticker == t)):
        raise HTTPException(404, "Unknown ticker")
    if db.scalar(select(func.count()).select_from(Alert).where(Alert.user_id == user.id)) >= 200:
        raise HTTPException(422, "Alert limit reached (200)")
    a = Alert(user_id=user.id, ticker=t, kind=data.kind, threshold=data.threshold, forms=data.forms.upper(),
              repeat=data.repeat, note=data.note.strip())
    a.last_seen_marker = alertsvc.initial_marker(db, a)
    db.add(a)
    db.commit()
    alertsvc.evaluate(db, [t])
    db.refresh(a)
    return a


class AlertPatch(BaseModel):
    active: bool | None = None
    repeat: bool | None = None


def _own_alert(db: Session, user: User, aid: int) -> Alert:
    a = db.scalar(select(Alert).where(Alert.id == aid, Alert.user_id == user.id))
    if a is None:
        raise HTTPException(404, "Alert not found")
    return a


@router.patch("/alerts/{aid}", response_model=AlertOut)
def patch_alert(aid: int, data: AlertPatch, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    a = _own_alert(db, user, aid)
    if data.active is not None:
        a.active = data.active
        if data.active:
            a.last_seen_marker = alertsvc.initial_marker(db, a)
    if data.repeat is not None:
        a.repeat = data.repeat
    db.commit()
    return a


@router.delete("/alerts/{aid}", status_code=204)
def delete_alert(aid: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    db.delete(_own_alert(db, user, aid))
    db.commit()


# ------------------------------------------------------------------ push
class PushSubIn(BaseModel):
    endpoint: str = Field(min_length=10, max_length=1000)
    keys: dict[str, str]

    @field_validator("endpoint")
    @classmethod
    def _https(cls, v: str) -> str:
        if not v.startswith("https://"):
            raise ValueError("Invalid push endpoint")
        return v


@router.get("/push/public-key")
def push_key(_: User = Depends(get_current_user)):
    try:
        return {"key": push.public_key()}
    except Exception as exc:  # cryptography/py_vapid missing or key file problem
        raise HTTPException(503, f"Web Push unavailable: {exc.__class__.__name__}")


@router.post("/push/subscriptions", status_code=201)
def subscribe(data: PushSubIn, request: Request, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    if not data.keys.get("p256dh") or not data.keys.get("auth"):
        raise HTTPException(422, "Missing subscription keys")
    s = db.scalar(select(PushSubscription).where(PushSubscription.endpoint == data.endpoint))
    if s is None:
        s = PushSubscription(endpoint=data.endpoint)
        db.add(s)
    s.user_id, s.p256dh, s.auth = user.id, data.keys["p256dh"][:255], data.keys["auth"][:255]
    s.user_agent = (request.headers.get("user-agent") or "")[:255]
    db.commit()
    return {"ok": True}


class PushUnsubIn(BaseModel):
    endpoint: str = Field(max_length=1000)


@router.post("/push/unsubscribe", status_code=204)
def unsubscribe(data: PushUnsubIn, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    s = db.scalar(select(PushSubscription).where(PushSubscription.endpoint == data.endpoint, PushSubscription.user_id == user.id))
    if s:
        db.delete(s)
        db.commit()


@router.get("/push/status")
def push_status(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    n = db.scalar(select(func.count()).select_from(PushSubscription).where(PushSubscription.user_id == user.id)) or 0
    return {"devices": n}


@router.post("/push/test")
def push_test(_db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    sent = push.send(user.id, "Investor Intelligence", "Test notification: push works on this device.", "/")
    return {"sent": sent}


# ------------------------------------------------------------------ jobs & security
@router.get("/admin/jobs")
def jobs(db: Session = Depends(get_db), _: User = Depends(require_admin)):
    runs = db.scalars(select(JobRun).order_by(JobRun.started_at.desc()).limit(40)).all()
    return {
        "enabled": get_settings().scheduler,
        "jobs": list(scheduler.JOBS),
        "runs": [{"id": r.id, "job": r.job, "started_at": r.started_at, "finished_at": r.finished_at, "status": r.status,
                  "message": r.message} for r in runs],
    }


@router.post("/admin/jobs/{name}/run")
def run_job_now(name: str, _: User = Depends(require_admin)):
    if name not in scheduler.JOBS:
        raise HTTPException(404, "Unknown job")
    r = scheduler.run_job(name)
    return {"job": r.job, "status": r.status, "message": r.message}


@router.get("/admin/security")
def security_check(request: Request, db: Session = Depends(get_db), _: User = Depends(require_admin)):
    s = get_settings()
    https = request.url.scheme == "https" or request.headers.get("x-forwarded-proto") == "https"
    host = (request.headers.get("host") or "").split(":")[0]
    local = host in ("localhost", "127.0.0.1") or host.endswith(".ts.net") or host.startswith(("192.168.", "10.", "100.")) or host.endswith(".local")
    admins = db.scalar(select(func.count()).select_from(User).where(User.role == "admin", User.is_active.is_(True))) or 0
    checks = [
        {"key": "https", "ok": https, "label": "Served over HTTPS",
         "advice": "Use `tailscale serve` or a reverse proxy with TLS. Needed for install, offline mode and push on phones."},
        {"key": "cookie_secure", "ok": s.cookie_secure or not https, "label": "Secure cookies when on HTTPS",
         "advice": "Set II_COOKIE_SECURE=true when serving over HTTPS."},
        {"key": "private_network", "ok": local, "label": f"Reached via a private address ({host or 'unknown'})",
         "advice": "Prefer a private network (Tailscale/WireGuard) over exposing the app to the internet."},
        {"key": "api_docs", "ok": not s.api_docs, "label": "API docs page disabled",
         "advice": "Leave II_API_DOCS=false unless you are developing."},
        {"key": "allowed_hosts", "ok": bool(s.allowed_hosts), "label": "Allowed host names configured",
         "advice": "Set II_ALLOWED_HOSTS to the names you use (e.g. myserver.tailnet.ts.net,localhost)."},
        {"key": "admins", "ok": admins <= 2, "label": f"{admins} active administrator account(s)",
         "advice": "Keep administrators to a minimum; members cannot see others' data either way."},
        {"key": "scheduler", "ok": s.scheduler, "label": "Automatic daily refresh and backups enabled",
         "advice": "Set II_SCHEDULER=true (default)."},
    ]
    return {"checks": checks, "host": host, "scheme": "https" if https else "http"}

