"""Market-wide screener from the SEC XBRL "frames" API (free, official, no key).

One request returns one concept for *all* US filers for one calendar period, e.g.
https://data.sec.gov/api/xbrl/frames/us-gaap/Revenues/USD/CY2024.json

The SEC aligns each company's fiscal year to the calendar period it most closely
fits, so for companies whose fiscal year does not end in December the "CY2024"
value is their fiscal year that best overlaps 2024. Only USD-reporting US-GAAP
filers are covered. Every row shows the period end date it comes from.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from ..db import utcnow
from ..models import DataSync, ScreenFact, Security
from . import prices, sec_client

FRAMES_URL = "https://data.sec.gov/api/xbrl/frames/us-gaap/{concept}/{unit}/{period}.json"
SOURCE = "sec_frames"

REVENUE = ("Revenues", "RevenueFromContractWithCustomerExcludingAssessedTax")
DURATION = [
    *[(c, "USD") for c in REVENUE],
    ("NetIncomeLoss", "USD"),
    ("OperatingIncomeLoss", "USD"),
    ("NetCashProvidedByUsedInOperatingActivities", "USD"),
    ("PaymentsToAcquirePropertyPlantAndEquipment", "USD"),
    ("EarningsPerShareDiluted", "USD-per-shares"),
]
PRIOR = [*[(c, "USD") for c in REVENUE], ("NetIncomeLoss", "USD"), ("EarningsPerShareDiluted", "USD-per-shares")]
INSTANT = [
    ("StockholdersEquity", "USD"),
    ("LongTermDebtNoncurrent", "USD"),
    ("AssetsCurrent", "USD"),
    ("LiabilitiesCurrent", "USD"),
    ("CashAndCashEquivalentsAtCarryingValue", "USD"),
]

METRICS = {
    # key: (label, kind)
    "revenue": ("Revenue", "money"),
    "revenue_growth": ("Revenue growth", "percent"),
    "net_income": ("Net income", "money"),
    "net_margin": ("Net margin", "percent"),
    "operating_margin": ("Operating margin", "percent"),
    "fcf": ("Free cash flow", "money"),
    "fcf_margin": ("FCF margin", "percent"),
    "roe": ("Return on equity", "percent"),
    "debt_to_equity": ("LT debt / equity", "ratio"),
    "current_ratio": ("Current ratio", "ratio"),
    "eps": ("Diluted EPS", "per_share"),
    "eps_growth": ("EPS growth", "percent"),
    "pe": ("P/E (stored close)", "ratio"),
}


def default_year(today: date | None = None) -> int:
    """Latest calendar year for which most annual reports are filed (10-Ks are due within ~60–90 days)."""
    today = today or date.today()
    return today.year - 1 if today.month >= 4 else today.year - 2


def plan(year: int) -> list[tuple[str, str, str]]:
    jobs = [(c, u, f"CY{year}") for c, u in DURATION]
    jobs += [(c, u, f"CY{year - 1}") for c, u in PRIOR]
    jobs += [(c, u, f"CY{year}Q4I") for c, u in INSTANT]
    return jobs


def parse_frame(payload: dict) -> list[dict]:
    out = []
    for r in payload.get("data") or []:
        try:
            out.append({
                "cik": int(r["cik"]),
                "entity_name": (r.get("entityName") or "")[:255],
                "value": Decimal(str(r["val"])),
                "end": date.fromisoformat(r["end"]) if r.get("end") else None,
                "accession": r.get("accn") or "",
            })
        except (KeyError, ValueError, ArithmeticError):
            continue
    return out


def sync(db: Session, year: int | None = None) -> DataSync:
    year = year or default_year()
    row = db.get(DataSync, SOURCE)
    if row is None:
        row = DataSync(source=SOURCE, source_url=FRAMES_URL.format(concept="{concept}", unit="{unit}", period="{period}"))
        db.add(row)
    row.last_attempt_at = utcnow()
    db.commit()
    errors, total = [], 0
    for concept, unit, period in plan(year):
        try:
            payload = sec_client.get_json(FRAMES_URL.format(concept=concept, unit=unit, period=period))
        except sec_client.SecError as exc:
            if exc.status == 404:
                continue  # concept/period not published (yet)
            errors.append(f"{concept} {period}: {exc}")
            if exc.status in (403, 429) or exc.status is None:
                break
            continue
        rows = parse_frame(payload)
        db.execute(delete(ScreenFact).where(ScreenFact.period == period, ScreenFact.concept == concept))
        db.bulk_insert_mappings(ScreenFact, [dict(period=period, concept=concept, **r) for r in rows])
        db.commit()
        total += len(rows)
    row = db.get(DataSync, SOURCE)
    row.record_count = total
    if errors and total == 0:
        row.status, row.message = "error", "; ".join(errors)[:1000]
    else:
        row.status, row.message, row.last_success_at = "ok", ("Partial: " + "; ".join(errors))[:1000] if errors else "", utcnow()
    row.source_url = f"SEC XBRL frames, CY{year} (+ CY{year - 1} for growth)"
    db.commit()
    _cache.clear()
    return row


# ------------------------------------------------------------------ compute
@dataclass
class Row:
    cik: int
    ticker: str | None
    name: str
    exchange: str | None
    period_end: date | None
    values: dict[str, Decimal | None]


_cache: dict[str, list[Row]] = {}


def _div(a, b):
    if a is None or b is None or b == 0:
        return None
    return a / b


def compute(db: Session, year: int) -> list[Row]:
    key = f"{year}"
    if key in _cache:
        return _cache[key]
    cy, py, inst = f"CY{year}", f"CY{year - 1}", f"CY{year}Q4I"
    data: dict[tuple[str, str], dict[int, ScreenFact]] = {}
    for f in db.scalars(select(ScreenFact).where(ScreenFact.period.in_([cy, py, inst]))):
        data.setdefault((f.period, f.concept), {})[f.cik] = f
    if not data:
        return []
    secs: dict[int, Security] = {}
    for s in db.scalars(select(Security).where(Security.is_listed.is_(True), Security.cik.is_not(None)).order_by(Security.id)):
        secs.setdefault(s.cik, s)

    def get(period, concept, cik):
        f = data.get((period, concept), {}).get(cik)
        return f.value if f else None

    ciks = set()
    for (period, _), m in data.items():
        if period == cy:
            ciks |= m.keys()
    tickers = [s.ticker for s in secs.values()]
    quotes = prices.latest_quotes(db, tickers) if tickers else {}
    rows: list[Row] = []
    for cik in ciks:
        rev_concept = next((c for c in REVENUE if get(cy, c, cik) is not None), None)
        rev = get(cy, rev_concept, cik) if rev_concept else None
        rev_prev = (get(py, rev_concept, cik) if rev_concept else None)
        ni, ni_prev = get(cy, "NetIncomeLoss", cik), get(py, "NetIncomeLoss", cik)
        op = get(cy, "OperatingIncomeLoss", cik)
        cfo, capex = get(cy, "NetCashProvidedByUsedInOperatingActivities", cik), get(cy, "PaymentsToAcquirePropertyPlantAndEquipment", cik)
        eps, eps_prev = get(cy, "EarningsPerShareDiluted", cik), get(py, "EarningsPerShareDiluted", cik)
        eq, ltd = get(inst, "StockholdersEquity", cik), get(inst, "LongTermDebtNoncurrent", cik)
        ca, cl = get(inst, "AssetsCurrent", cik), get(inst, "LiabilitiesCurrent", cik)
        fcf = cfo - capex if cfo is not None and capex is not None else None
        sec = secs.get(cik)
        q = quotes.get(sec.ticker) if sec else None
        v = {
            "revenue": rev,
            "revenue_growth": (rev / rev_prev - 1) if rev is not None and rev_prev and rev_prev > 0 else None,
            "net_income": ni,
            "net_margin": _div(ni, rev) if rev and rev > 0 else None,
            "operating_margin": _div(op, rev) if rev and rev > 0 else None,
            "fcf": fcf,
            "fcf_margin": _div(fcf, rev) if rev and rev > 0 else None,
            "roe": _div(ni, eq) if eq and eq > 0 else None,
            "debt_to_equity": _div(ltd, eq) if eq and eq > 0 else None,
            "current_ratio": _div(ca, cl),
            "eps": eps,
            "eps_growth": (eps / eps_prev - 1) if eps is not None and eps_prev and eps_prev > 0 else None,
            "pe": (q["close"] / eps) if q and q["currency"] == "USD" and eps and eps > 0 else None,
        }
        any_fact = next((m[cik] for (p, _), m in data.items() if p == cy and cik in m), None)
        rows.append(Row(cik=cik, ticker=sec.ticker if sec else None, name=sec.name if sec else (any_fact.entity_name if any_fact else ""),
                        exchange=sec.exchange if sec else None, period_end=any_fact.end if any_fact else None, values=v))
    _cache[key] = rows
    return rows


def available_years(db: Session) -> list[int]:
    periods = db.scalars(select(ScreenFact.period).distinct()).all()
    years = sorted({int(p[2:6]) for p in periods if len(p) == 6}, reverse=True)
    return [y for y in years if f"CY{y}" in periods]
