"""SEC EDGAR reference data (free, official, no API key).

Source: https://www.sec.gov/files/company_tickers_exchange.json
Format: {"fields": ["cik", "name", "ticker", "exchange"], "data": [[...], ...]}

SEC fair-access policy (https://www.sec.gov/os/accessing-edgar-data):
* at most 10 requests per second per user,
* automated requests must declare a User-Agent with a contact e-mail.
A sync makes exactly one request, and we refuse to sync more often than
``min_sync_interval_seconds`` (the file is regenerated about daily).
"""

from datetime import timedelta

import httpx
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from ..config import get_settings
from ..db import utcnow
from ..models import DataSync, Security

SOURCE = "sec_company_tickers_exchange"
SOURCE_URL = "https://www.sec.gov/files/company_tickers_exchange.json"


class SyncError(RuntimeError):
    pass


def get_sync_row(db: Session) -> DataSync:
    row = db.get(DataSync, SOURCE)
    if row is None:
        row = DataSync(source=SOURCE, source_url=SOURCE_URL)
        db.add(row)
        db.flush()
    return row


def parse_payload(payload: dict) -> list[dict]:
    """Validate and normalise the SEC payload. Rows with missing tickers or
    names are skipped rather than guessed."""
    try:
        fields = payload["fields"]
        rows = payload["data"]
        idx = {name: fields.index(name) for name in ("cik", "name", "ticker", "exchange")}
    except (KeyError, ValueError, TypeError) as exc:
        raise SyncError("Unexpected SEC file format") from exc

    out: dict[str, dict] = {}
    for row in rows:
        ticker = (row[idx["ticker"]] or "").strip().upper()
        name = (row[idx["name"]] or "").strip()
        if not ticker or not name:
            continue
        cik = row[idx["cik"]]
        exchange = row[idx["exchange"]]
        out.setdefault(
            ticker,
            {
                "ticker": ticker,
                "name": name,
                "cik": int(cik) if cik is not None else None,
                "exchange": (exchange or None),
            },
        )
    if not out:
        raise SyncError("SEC file contained no usable rows")
    return list(out.values())


def fetch_payload(user_agent: str, client: httpx.Client | None = None) -> dict:
    headers = {"User-Agent": user_agent, "Accept-Encoding": "gzip, deflate"}
    own = client is None
    client = client or httpx.Client(timeout=30)
    try:
        resp = client.get(SOURCE_URL, headers=headers)
    except httpx.HTTPError as exc:
        raise SyncError(f"Network error contacting SEC: {exc}") from exc
    finally:
        if own:
            client.close()
    if resp.status_code == 403:
        raise SyncError("SEC refused the request (403). Check II_SEC_USER_AGENT contains a name and contact e-mail.")
    if resp.status_code == 429:
        raise SyncError("SEC rate limit reached (429). Try again later.")
    if resp.status_code != 200:
        raise SyncError(f"SEC returned HTTP {resp.status_code}")
    try:
        return resp.json()
    except ValueError as exc:
        raise SyncError("SEC response was not valid JSON") from exc


def upsert_securities(db: Session, rows: list[dict]) -> int:
    now = utcnow()
    existing = {s.ticker: s for s in db.scalars(select(Security).where(Security.source == SOURCE))}
    seen = set()
    for r in rows:
        seen.add(r["ticker"])
        sec = existing.get(r["ticker"])
        if sec is None:
            # A ticker might exist from another source; don't duplicate it.
            sec = db.scalar(select(Security).where(Security.ticker == r["ticker"]))
        if sec is None:
            db.add(Security(source=SOURCE, updated_at=now, is_listed=True, **r))
        else:
            sec.name, sec.cik, sec.exchange = r["name"], r["cik"], r["exchange"]
            sec.source, sec.is_listed, sec.updated_at = SOURCE, True, now
    missing = [t for t in existing if t not in seen]
    if missing:
        # Keep the rows (watchlists may reference them) but flag as no longer listed.
        for i in range(0, len(missing), 500):
            db.execute(
                update(Security).where(Security.ticker.in_(missing[i : i + 500])).values(is_listed=False, updated_at=now)
            )
    return len(rows)


def sync_securities(db: Session, *, force: bool = False, client: httpx.Client | None = None) -> DataSync:
    settings = get_settings()
    row = get_sync_row(db)
    now = utcnow()
    if (
        not force
        and row.last_attempt_at is not None
        and now - row.last_attempt_at < timedelta(seconds=settings.min_sync_interval_seconds)
    ):
        wait = settings.min_sync_interval_seconds - int((now - row.last_attempt_at).total_seconds())
        raise SyncError(f"Synced recently. Please wait {max(wait // 60, 1)} more minute(s).")
    if "@" not in settings.sec_user_agent:
        raise SyncError(
            "Set II_SEC_USER_AGENT to a name and contact e-mail (required by the SEC fair-access policy)."
        )
    row.last_attempt_at = now
    try:
        rows = parse_payload(fetch_payload(settings.sec_user_agent, client))
        count = upsert_securities(db, rows)
    except SyncError as exc:
        db.rollback()
        row = get_sync_row(db)
        row.last_attempt_at = now
        row.status, row.message = "error", str(exc)
        db.commit()
        raise
    row.status, row.message, row.record_count, row.last_success_at = "ok", "", count, now
    db.commit()
    return row
