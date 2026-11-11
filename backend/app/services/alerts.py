"""Private user alerts, evaluated against stored data only.

* price_above / price_below: latest stored end-of-day close vs threshold.
* daily_move: |close / previous stored close − 1| ≥ threshold (fraction).
* filing: a new SEC filing (optionally of given forms) appeared in the stored filing index.

Each alert remembers the last price date / filing it evaluated, so it fires at most once
per new data point. One-shot alerts deactivate after firing; "repeat" alerts re-arm.
"""

from __future__ import annotations

from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db import utcnow
from ..models import Alert, Filing, Security
from ..notify import notify
from .prices import latest_quotes

KINDS = ("price_above", "price_below", "daily_move", "filing")


def _latest_filing(db: Session, cik: int, forms: list[str]) -> Filing | None:
    stmt = select(Filing).where(Filing.cik == cik)
    if forms:
        stmt = stmt.where(Filing.form.in_(forms))
    return db.scalar(stmt.order_by(Filing.filing_date.desc(), Filing.accession.desc()).limit(1))


def initial_marker(db: Session, alert: Alert) -> str:
    """Set at creation so that only *new* data triggers the alert."""
    if alert.kind == "filing":
        sec = db.scalar(select(Security).where(Security.ticker == alert.ticker))
        f = _latest_filing(db, sec.cik, _forms(alert)) if sec and sec.cik else None
        return f.accession if f else ""
    return ""  # price alerts: the current close counts (user wants to know if already crossed)


def _forms(alert: Alert) -> list[str]:
    return [f.strip().upper() for f in alert.forms.split(",") if f.strip()]


def evaluate(db: Session, tickers: list[str] | None = None) -> int:
    """Evaluate active alerts (optionally only for some tickers). Returns number triggered."""
    stmt = select(Alert).where(Alert.active.is_(True))
    if tickers:
        stmt = stmt.where(Alert.ticker.in_([t.upper() for t in tickers]))
    alerts = db.scalars(stmt).all()
    if not alerts:
        return 0
    quotes = latest_quotes(db, sorted({a.ticker for a in alerts if a.kind != "filing"}))
    fired = 0
    now = utcnow()
    for a in alerts:
        a.last_checked_at = now
        title = body = ""
        if a.kind == "filing":
            sec = db.scalar(select(Security).where(Security.ticker == a.ticker))
            f = _latest_filing(db, sec.cik, _forms(a)) if sec and sec.cik else None
            if f is None or f.accession == a.last_seen_marker:
                continue
            new = db.scalars(
                select(Filing).where(Filing.cik == sec.cik, *( [Filing.form.in_(_forms(a))] if _forms(a) else [] ))
                .order_by(Filing.filing_date.desc()).limit(10)
            ).all()
            fresh = []
            for x in new:
                if x.accession == a.last_seen_marker:
                    break
                fresh.append(x)
            a.last_seen_marker = f.accession
            if not fresh:
                continue
            title = f"{a.ticker}: new {fresh[0].form} filing"
            body = ", ".join(f"{x.form} ({x.filing_date.isoformat()})" for x in fresh[:5]) + " — SEC EDGAR"
        else:
            q = quotes.get(a.ticker)
            if q is None or a.last_seen_marker == q["date"].isoformat():
                continue
            a.last_seen_marker = q["date"].isoformat()
            close, thr = q["close"], a.threshold or Decimal(0)
            if a.kind == "price_above" and close >= thr:
                title, body = f"{a.ticker} closed at {close} {q['currency']}", f"At or above your level {thr} (close of {q['date']}, end of day)."
            elif a.kind == "price_below" and close <= thr:
                title, body = f"{a.ticker} closed at {close} {q['currency']}", f"At or below your level {thr} (close of {q['date']}, end of day)."
            elif a.kind == "daily_move" and q["change_pct"] is not None and abs(q["change_pct"]) >= thr:
                pct = q["change_pct"] * 100
                title = f"{a.ticker} moved {pct:+.2f}%"
                body = f"Close {close} on {q['date']} vs {q['prev_close']} on {q['prev_date']} (stored end-of-day closes)."
            else:
                continue
        if a.note:
            body += f" Note: {a.note}"
        notify(db, a.user_id, "alert", title, body, f"/company?t={a.ticker}", push=True)
        a.last_triggered_at = now
        if not a.repeat:
            a.active = False
        fired += 1
    db.commit()
    return fired
