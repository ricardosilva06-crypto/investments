"""End-of-day prices. Never real-time.

Two ways to get prices, both free:

1. **CSV import** (always available, admin only): any daily OHLC file, e.g. an
   export from your broker. The source name you provide is stored with each bar.
2. **Tiingo** (optional): only active when ``II_TIINGO_API_KEY`` is set. Tiingo's free
   plan requires an account (no card), is licensed for internal/personal use, and is
   limited per hour and per day. We stay under a configurable budget
   (default 40 requests/hour, 400/day) and refresh a ticker at most every 12 hours.
"""

from __future__ import annotations

import csv
import io
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal, InvalidOperation

import httpx
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..config import get_settings
from ..db import utcnow
from ..models import FetchState, PriceBar, ProviderUsage

TIINGO = "tiingo"
TIINGO_URL = "https://api.tiingo.com/tiingo/daily/{ticker}/prices"
REFRESH_AFTER = timedelta(hours=12)
ERROR_BACKOFF = timedelta(minutes=30)

client_factory = lambda: httpx.Client(timeout=20)  # noqa: E731  (tests override)


class PriceError(RuntimeError):
    pass


# ------------------------------------------------------------------ budget
def _hour(now: datetime) -> datetime:
    return now.replace(minute=0, second=0, microsecond=0)


def usage(db: Session, provider: str) -> dict:
    now = utcnow()
    hour = db.scalar(select(ProviderUsage.requests).where(ProviderUsage.provider == provider, ProviderUsage.hour == _hour(now))) or 0
    day = (
        db.scalar(
            select(func.coalesce(func.sum(ProviderUsage.requests), 0)).where(
                ProviderUsage.provider == provider, ProviderUsage.hour >= now - timedelta(hours=24)
            )
        )
        or 0
    )
    s = get_settings()
    return {"hour": hour, "day": day, "hour_limit": s.tiingo_max_per_hour, "day_limit": s.tiingo_max_per_day}


def _consume(db: Session, provider: str) -> None:
    u = usage(db, provider)
    if u["hour"] >= u["hour_limit"] or u["day"] >= u["day_limit"]:
        raise PriceError(
            f"Request budget for {provider} reached ({u['hour']}/{u['hour_limit']} this hour, "
            f"{u['day']}/{u['day_limit']} in 24 h). Showing stored prices."
        )
    h = _hour(utcnow())
    row = db.scalar(select(ProviderUsage).where(ProviderUsage.provider == provider, ProviderUsage.hour == h))
    if row is None:
        db.add(ProviderUsage(provider=provider, hour=h, requests=1))
    else:
        row.requests += 1
    db.commit()


# ------------------------------------------------------------------ helpers
def _dec(v) -> Decimal | None:
    if v is None or v == "":
        return None
    try:
        d = Decimal(str(v).strip().replace(",", "."))
    except InvalidOperation:
        return None
    return d if d.is_finite() else None


def upsert_bars(db: Session, ticker: str, bars: list[dict], source: str, currency: str) -> int:
    if not bars:
        return 0
    days = [b["day"] for b in bars]
    existing = {
        b.day: b
        for b in db.scalars(select(PriceBar).where(PriceBar.ticker == ticker, PriceBar.day.in_(days)))
    }
    now = utcnow()
    for b in bars:
        row = existing.get(b["day"])
        if row is None:
            db.add(PriceBar(ticker=ticker, source=source, currency=currency, fetched_at=now, **b))
        else:
            for k, v in b.items():
                setattr(row, k, v)
            row.source, row.currency, row.fetched_at = source, currency, now
    return len(bars)


def provider_configured() -> bool:
    return bool(get_settings().tiingo_api_key)


# ------------------------------------------------------------------ tiingo
def _tiingo_symbol(ticker: str) -> str:
    return ticker.replace(".", "-").lower()


def parse_tiingo(rows: list) -> list[dict]:
    out = []
    for r in rows:
        try:
            day = date.fromisoformat(str(r["date"])[:10])
        except (KeyError, ValueError):
            continue
        close = _dec(r.get("close"))
        if close is None:
            continue
        vol = r.get("volume")
        out.append(
            dict(day=day, open=_dec(r.get("open")), high=_dec(r.get("high")), low=_dec(r.get("low")), close=close,
                 adj_close=_dec(r.get("adjClose")), volume=int(vol) if isinstance(vol, (int, float)) else None)
        )
    return out


def fetch_tiingo(db: Session, ticker: str, start: date) -> list[dict]:
    key = get_settings().tiingo_api_key
    if not key:
        raise PriceError("No price provider configured.")
    _consume(db, TIINGO)
    try:
        with client_factory() as c:
            resp = c.get(
                TIINGO_URL.format(ticker=_tiingo_symbol(ticker)),
                params={"startDate": start.isoformat()},
                headers={"Authorization": f"Token {key}", "Content-Type": "application/json"},
            )
    except httpx.HTTPError as exc:
        raise PriceError(f"Network error contacting Tiingo ({exc.__class__.__name__})") from exc
    if resp.status_code == 404:
        raise PriceError(f"Tiingo has no end-of-day data for {ticker}.")
    if resp.status_code in (401, 403):
        raise PriceError("Tiingo rejected the API key.")
    if resp.status_code == 429:
        raise PriceError("Tiingo rate limit reached. Showing stored prices.")
    if resp.status_code != 200:
        raise PriceError(f"Tiingo returned HTTP {resp.status_code}")
    try:
        data = resp.json()
    except ValueError as exc:
        raise PriceError("Tiingo response was not valid JSON") from exc
    if not isinstance(data, list):
        raise PriceError("Unexpected Tiingo response")
    return parse_tiingo(data)


def _state(db: Session, ticker: str) -> FetchState:
    st = db.scalar(select(FetchState).where(FetchState.source == f"prices_{TIINGO}", FetchState.key == ticker))
    if st is None:
        st = FetchState(source=f"prices_{TIINGO}", key=ticker)
        db.add(st)
        db.flush()
    return st


def maybe_refresh(db: Session, ticker: str) -> str | None:
    """Refresh from the optional provider when stale. Returns an error message or None."""
    if not provider_configured():
        return None
    st = _state(db, ticker)
    now = utcnow()
    if st.last_attempt_at and (
        (st.status == "ok" and now - st.last_attempt_at < REFRESH_AFTER)
        or (st.status != "ok" and now - st.last_attempt_at < ERROR_BACKOFF)
    ):
        db.commit()
        return st.message or None
    last = db.scalar(select(func.max(PriceBar.day)).where(PriceBar.ticker == ticker))
    start = (last - timedelta(days=7)) if last else (now.date() - timedelta(days=365 * 5))
    st.last_attempt_at = now
    try:
        bars = fetch_tiingo(db, ticker, start)
        upsert_bars(db, ticker, bars, source="Tiingo (end of day)", currency="USD")
        st.status, st.message, st.last_success_at = "ok", "", now
    except PriceError as exc:
        st.status, st.message = "error", str(exc)
    db.commit()
    return st.message or None


# ------------------------------------------------------------------ csv
HEADER_ALIASES = {
    "date": ("date", "day", "data", "datum", "time", "timestamp"),
    "open": ("open", "otwarcie", "abertura"),
    "high": ("high", "najwyzszy", "max"),
    "low": ("low", "najnizszy", "min"),
    "close": ("close", "zamkniecie", "fecho", "price", "last"),
    "adj_close": ("adj close", "adj_close", "adjclose", "adjusted close"),
    "volume": ("volume", "wolumen", "vol"),
}


def parse_csv(text: str) -> list[dict]:
    """Parse a daily OHLC CSV with a header row (comma or semicolon separated)."""
    sample = text[:2048]
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=",;\t")
    except csv.Error:
        dialect = csv.excel
    reader = csv.reader(io.StringIO(text), dialect)
    try:
        header = [h.strip().lower().lstrip("﻿") for h in next(reader)]
    except StopIteration:
        raise PriceError("The file is empty.")
    cols: dict[str, int] = {}
    for key, aliases in HEADER_ALIASES.items():
        for i, h in enumerate(header):
            if h in aliases:
                cols[key] = i
                break
    if "date" not in cols or "close" not in cols:
        raise PriceError("CSV needs a header with at least 'Date' and 'Close' columns.")
    bars, errors = [], 0
    for n, row in enumerate(reader, start=2):
        if not row or all(not c.strip() for c in row):
            continue
        try:
            raw = row[cols["date"]].strip()
            day = date.fromisoformat(raw[:10]) if "-" in raw else datetime.strptime(raw, "%Y%m%d").date()
        except (ValueError, IndexError):
            errors += 1
            continue

        def get(k):
            return _dec(row[cols[k]]) if k in cols and cols[k] < len(row) else None

        close = get("close")
        if close is None or close <= 0:
            errors += 1
            continue
        vol = get("volume")
        bars.append(dict(day=day, open=get("open"), high=get("high"), low=get("low"), close=close,
                         adj_close=get("adj_close"), volume=int(vol) if vol is not None else None))
    if not bars:
        raise PriceError("No valid rows found in the CSV.")
    if errors > max(5, len(bars) // 10):
        raise PriceError(f"{errors} rows could not be parsed. Check the date format (YYYY-MM-DD) and decimals.")
    today = datetime.now(UTC).date()
    if any(b["day"] > today for b in bars):
        raise PriceError("The file contains dates in the future.")
    return bars


# ------------------------------------------------------------------ read
RANGES = {"1m": 31, "3m": 92, "6m": 183, "1y": 366, "5y": 366 * 5 + 2, "max": None}


def get_bars(db: Session, ticker: str, rng: str = "1y") -> list[PriceBar]:
    stmt = select(PriceBar).where(PriceBar.ticker == ticker)
    days = RANGES.get(rng, 366)
    if days:
        last = db.scalar(select(func.max(PriceBar.day)).where(PriceBar.ticker == ticker))
        if last:
            stmt = stmt.where(PriceBar.day >= last - timedelta(days=days))
    return list(db.scalars(stmt.order_by(PriceBar.day)))


def latest_quotes(db: Session, tickers: list[str]) -> dict[str, dict]:
    """Last two stored closes per ticker -> close, change, date and source."""
    if not tickers:
        return {}
    out: dict[str, dict] = {}
    ranked = (
        select(
            PriceBar.ticker, PriceBar.day, PriceBar.close, PriceBar.source, PriceBar.currency,
            func.row_number().over(partition_by=PriceBar.ticker, order_by=PriceBar.day.desc()).label("rn"),
        )
        .where(PriceBar.ticker.in_(tickers))
        .subquery()
    )
    rows = db.execute(select(ranked).where(ranked.c.rn <= 2).order_by(ranked.c.ticker, ranked.c.rn)).all()
    for t, day, close, source, ccy, rn in rows:
        close = Decimal(close)
        if rn == 1:
            out[t] = {"close": close, "date": day, "source": source, "currency": ccy, "prev_close": None, "prev_date": None}
        elif t in out:
            out[t]["prev_close"], out[t]["prev_date"] = close, day
    for q in out.values():
        pc = q["prev_close"]
        q["change"] = q["close"] - pc if pc else None
        q["change_pct"] = (q["close"] / pc - 1) if pc else None
    return out
