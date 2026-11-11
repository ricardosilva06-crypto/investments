"""ECB euro foreign exchange reference rates (free, no key).

API: https://data-api.ecb.europa.eu/service/data/EXR/D.{CCY+CCY}.EUR.SP00.A
Rates are published once per TARGET working day around 16:00 CET; they are
reference rates for information purposes, not trading rates.
ECB statistics may be reused free of charge provided the source is acknowledged.
"""

import csv
import io
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db import utcnow
from ..models import DataSync, FxRate

SOURCE = "ecb_exr"
CURRENCIES = ["USD", "GBP", "CHF", "JPY", "SEK", "NOK", "DKK", "PLN", "CZK", "HUF", "CAD", "AUD", "BRL", "CNY"]
URL = "https://data-api.ecb.europa.eu/service/data/EXR/D.{ccys}.EUR.SP00.A"
REFRESH_AFTER = timedelta(hours=6)

client_factory = lambda: httpx.Client(timeout=20)  # noqa: E731


class EcbError(RuntimeError):
    pass


def parse_csv(text: str) -> list[dict]:
    reader = csv.DictReader(io.StringIO(text))
    out = []
    for r in reader:
        try:
            ccy = r["CURRENCY"].strip()
            day = date.fromisoformat(r["TIME_PERIOD"].strip())
            value = Decimal(r["OBS_VALUE"].strip())
        except (KeyError, ValueError, InvalidOperation, AttributeError):
            continue
        if len(ccy) == 3 and value > 0:
            out.append({"currency": ccy, "day": day, "value": value})
    return out


def sync(db: Session, force: bool = False) -> DataSync:
    row = db.get(DataSync, SOURCE)
    url = URL.format(ccys="+".join(CURRENCIES))
    if row is None:
        row = DataSync(source=SOURCE, source_url=url)
        db.add(row)
        db.flush()
    now = utcnow()
    if not force and row.last_attempt_at and now - row.last_attempt_at < REFRESH_AFTER:
        return row
    row.last_attempt_at = now
    try:
        with client_factory() as c:
            resp = c.get(url, params={"lastNObservations": 30, "format": "csvdata"}, headers={"Accept": "text/csv"})
        if resp.status_code != 200:
            raise EcbError(f"ECB returned HTTP {resp.status_code}")
        rates = parse_csv(resp.text)
        if not rates:
            raise EcbError("ECB response contained no rates")
    except (httpx.HTTPError, EcbError) as exc:
        row.status, row.message = "error", str(exc) if isinstance(exc, EcbError) else f"Network error ({exc.__class__.__name__})"
        db.commit()
        return row
    existing = {
        (f.currency, f.day): f for f in db.scalars(select(FxRate).where(FxRate.day >= min(r["day"] for r in rates)))
    }
    for r in rates:
        f = existing.get((r["currency"], r["day"]))
        if f is None:
            db.add(FxRate(**r))
        else:
            f.value = r["value"]
    row.status, row.message, row.record_count, row.last_success_at = "ok", "", len(rates), now
    db.commit()
    return row


def latest(db: Session) -> list[dict]:
    out = []
    for ccy in CURRENCIES:
        rows = list(db.scalars(select(FxRate).where(FxRate.currency == ccy).order_by(FxRate.day.desc()).limit(2)))
        if not rows:
            continue
        cur, prev = rows[0], rows[1] if len(rows) > 1 else None
        out.append({
            "currency": ccy,
            "date": cur.day.isoformat(),
            "value": format(cur.value, "f"),
            "prev_value": format(prev.value, "f") if prev else None,
            "change_pct": format((cur.value / prev.value - 1).quantize(Decimal("0.000001")), "f") if prev else None,
        })
    return out


def history(db: Session, ccy: str) -> list[dict]:
    rows = db.scalars(select(FxRate).where(FxRate.currency == ccy).order_by(FxRate.day))
    return [{"date": r.day.isoformat(), "value": format(r.value, "f")} for r in rows]
