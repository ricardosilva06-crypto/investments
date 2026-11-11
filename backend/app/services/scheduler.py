"""In-process background scheduler (no cron, no paid service).

Jobs (UTC):
* feeds          every 30 min   poll RSS/Atom feeds that are due
* fx             every 6 h      ECB reference rates
* daily_refresh  daily          SEC data + optional prices for watched/held/alerted tickers, then alerts
* backup         daily          zip of database + PDFs (keeps II_BACKUPS_KEEP)

Only one process runs the scheduler (file lock in the data directory). Every run
is recorded in ``job_runs`` and visible to administrators.
"""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable
from datetime import datetime, timedelta

from sqlalchemy import select

from ..config import get_settings
from ..db import session_factory, utcnow
from ..models import Alert, JobRun, Portfolio, Security, Transaction, Watchlist, WatchlistItem
from . import alerts, backup, ecb, fundamentals, news, prices, sec_client

log = logging.getLogger(__name__)
_thread: threading.Thread | None = None
_stop = threading.Event()
_lock_file = None


def tracked_tickers(db) -> list[Security]:
    """Tickers anyone watches, holds or has an alert on."""
    tickers = set(db.scalars(select(Security.ticker).join(WatchlistItem, WatchlistItem.security_id == Security.id)))
    tickers |= set(db.scalars(select(Transaction.symbol).join(Portfolio)))
    tickers |= set(db.scalars(select(Alert.ticker).where(Alert.active.is_(True))))
    if not tickers:
        return []
    return list(db.scalars(select(Security).where(Security.ticker.in_(tickers))))


def job_daily_refresh(db) -> str:
    secs = tracked_tickers(db)
    refreshed, errors = 0, 0
    for s in secs:
        if s.cik:
            try:
                errs = fundamentals.refresh_company(db, s.cik)
                errors += bool(errs)
                refreshed += 1
            except sec_client.SecError:
                errors += 1
        prices.maybe_refresh(db, s.ticker)
    ecb.sync(db)
    fired = alerts.evaluate(db)
    return f"{refreshed} companies checked ({errors} with errors), {fired} alerts triggered"


def job_feeds(db) -> str:
    return f"{news.fetch_all(db)} new items"


def job_fx(db) -> str:
    row = ecb.sync(db)
    return f"ECB: {row.status} {row.message}".strip()


def job_backup(db) -> str:
    return f"wrote {backup.create_backup().name}"


JOBS: dict[str, Callable] = {
    "daily_refresh": job_daily_refresh,
    "feeds": job_feeds,
    "fx": job_fx,
    "backup": job_backup,
}


def run_job(name: str) -> JobRun:
    db = session_factory()()
    try:
        run = JobRun(job=name)
        db.add(run)
        db.commit()
        try:
            msg = JOBS[name](db)
            run = db.get(JobRun, run.id)
            run.status, run.message = "ok", msg[:2000]
        except Exception as exc:  # a failing job must never kill the scheduler
            db.rollback()
            log.exception("job %s failed", name)
            run = db.get(JobRun, run.id)
            run.status, run.message = "error", f"{exc.__class__.__name__}: {exc}"[:2000]
        run.finished_at = utcnow()
        db.commit()
        db.expunge(run)
        return run
    finally:
        db.close()


def _last_start(db, name: str) -> datetime | None:
    return db.scalar(select(JobRun.started_at).where(JobRun.job == name).order_by(JobRun.started_at.desc()).limit(1))


def due_jobs(now: datetime, last: dict[str, datetime | None]) -> list[str]:
    s = get_settings()
    out = []
    if last.get("feeds") is None or now - last["feeds"] >= timedelta(minutes=30):
        out.append("feeds")
    if last.get("fx") is None or now - last["fx"] >= timedelta(hours=6):
        out.append("fx")
    for name, hour in (("daily_refresh", s.daily_job_hour_utc), ("backup", s.backup_hour_utc)):
        today_slot = now.replace(hour=hour, minute=0, second=0, microsecond=0)
        if now >= today_slot and (last.get(name) is None or last[name] < today_slot):
            out.append(name)
    return out


def _loop() -> None:
    time.sleep(20)  # let the app start
    while not _stop.is_set():
        try:
            db = session_factory()()
            try:
                last = {n: _last_start(db, n) for n in JOBS}
            finally:
                db.close()
            for name in due_jobs(utcnow(), last):
                if _stop.is_set():
                    break
                run_job(name)
        except Exception:
            log.exception("scheduler loop error")
        _stop.wait(60)


def start() -> bool:
    """Start the scheduler thread if enabled and no other process holds the lock."""
    global _thread, _lock_file
    s = get_settings()
    if not s.scheduler or (_thread and _thread.is_alive()):
        return False
    s.data_dir.mkdir(parents=True, exist_ok=True)
    _lock_file = open(s.data_dir / "scheduler.lock", "w")
    try:
        try:
            import fcntl  # Linux / macOS

            fcntl.flock(_lock_file, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except ImportError:  # Windows
            import msvcrt

            msvcrt.locking(_lock_file.fileno(), msvcrt.LK_NBLCK, 1)
    except OSError:
        return False  # another worker runs it
    _stop.clear()
    _thread = threading.Thread(target=_loop, name="scheduler", daemon=True)
    _thread.start()
    return True


def stop() -> None:
    _stop.set()
