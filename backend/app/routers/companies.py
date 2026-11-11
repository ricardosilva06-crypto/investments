"""Company research: SEC profile, filings, financial statements and prices."""

import json
from datetime import date, datetime
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db import get_db
from ..deps import get_current_user, require_admin
from ..models import CompanyProfile, FinancialFact, Filing, Security, User
from ..schemas import QuoteOut, SecurityOut
from ..services import alerts as alertsvc
from ..services import ecb, fundamentals, prices

router = APIRouter(prefix="/api", tags=["companies"])

KEY_FORMS = ("10-K", "10-Q", "8-K", "20-F", "6-K", "40-F", "DEF 14A", "S-1", "10-K/A", "10-Q/A")


def get_security(db: Session, ticker: str) -> Security:
    s = db.scalar(select(Security).where(Security.ticker == ticker.strip().upper()))
    if s is None:
        raise HTTPException(404, "Security not found")
    return s


class FreshnessOut(BaseModel):
    source: str
    status: str
    message: str
    last_success_at: datetime | None


class ProfileOut(BaseModel):
    cik: int
    name: str
    entity_type: str
    sic: str
    sic_description: str
    category: str
    fiscal_year_end: str
    state_of_incorporation: str
    business_address: str
    phone: str
    website: str
    investor_website: str
    tickers: list[str]
    exchanges: list[str]
    former_names: list[dict]


class KeyFigure(BaseModel):
    key: str
    label: str
    kind: str
    value: str
    period_end: str
    derived: bool
    formula: str
    concept: str
    form: str
    filed: str | None


class CompanyOut(BaseModel):
    security: SecurityOut
    profile: ProfileOut | None
    freshness: list[FreshnessOut]
    errors: dict[str, str]
    quote: QuoteOut | None
    key_figures: list[KeyFigure]
    currency: str
    has_financials: bool


def _freshness(db: Session, cik: int) -> list[FreshnessOut]:
    out = []
    for src in ("sec_submissions", "sec_companyfacts"):
        st = fundamentals.get_state(db, src, cik)
        out.append(
            FreshnessOut(source=src, status=st.status if st else "never", message=st.message if st else "",
                         last_success_at=st.last_success_at if st else None)
        )
    return out


def _facts(db: Session, cik: int | None) -> list[FinancialFact]:
    if not cik:
        return []
    return list(db.scalars(select(FinancialFact).where(FinancialFact.cik == cik)))


def _key_figures(facts: list[FinancialFact]) -> tuple[list[KeyFigure], str]:
    if not facts:
        return [], "USD"
    out: list[KeyFigure] = []
    stmts = {
        "income": fundamentals.build_statement(facts, "income", "annual", limit=2),
        "cashflow": fundamentals.build_statement(facts, "cashflow", "annual", limit=2),
        "balance": fundamentals.build_statement(facts, "balance", "annual", limit=2),
        "metrics": fundamentals.build_metrics(facts, "annual"),
    }
    wanted = [
        ("income", "revenue"), ("income", "net_income"), ("income", "eps_diluted"), ("metrics", "revenue_growth"),
        ("metrics", "operating_margin"), ("metrics", "net_margin"), ("metrics", "fcf"), ("metrics", "roe"),
        ("balance", "cash"), ("balance", "long_term_debt"),
    ]
    for stmt, key in wanted:
        s = stmts[stmt]
        row = next((r for r in s["rows"] if r["key"] == key), None)
        if not row or not s["periods"]:
            continue
        cell = row["values"][0]
        if cell is None:
            continue
        out.append(KeyFigure(key=key, label=row["label"], kind=row["kind"], value=cell["value"],
                             period_end=s["periods"][0]["end"], derived=cell["derived"], formula=cell["formula"],
                             concept=cell["concept"], form=cell["form"], filed=cell["filed"]))
    return out, stmts["income"]["currency"]


def _profile_out(p: CompanyProfile | None) -> ProfileOut | None:
    if p is None:
        return None
    try:
        former = json.loads(p.former_names or "[]")
    except ValueError:
        former = []
    return ProfileOut(
        cik=p.cik, name=p.name, entity_type=p.entity_type, sic=p.sic, sic_description=p.sic_description,
        category=p.category, fiscal_year_end=p.fiscal_year_end, state_of_incorporation=p.state_of_incorporation,
        business_address=p.business_address, phone=p.phone, website=p.website, investor_website=p.investor_website,
        tickers=[t for t in p.tickers.split(",") if t], exchanges=[e for e in p.exchanges.split(",") if e],
        former_names=former if isinstance(former, list) else [],
    )


@router.get("/companies/{ticker}", response_model=CompanyOut)
def company(ticker: str, db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    s = get_security(db, ticker)
    errors: dict[str, str] = {}
    if s.cik:
        try:
            errors = fundamentals.refresh_company(db, s.cik)
        except fundamentals.sec_client.SecError as exc:  # e.g. User-Agent not configured
            errors = {"sec": str(exc)}
    price_error = prices.maybe_refresh(db, s.ticker)
    if price_error:
        errors["prices"] = price_error
    alertsvc.evaluate(db, [s.ticker])
    facts = _facts(db, s.cik)
    figures, ccy = _key_figures(facts)
    q = prices.latest_quotes(db, [s.ticker]).get(s.ticker)
    return CompanyOut(
        security=s,
        profile=_profile_out(db.get(CompanyProfile, s.cik) if s.cik else None),
        freshness=_freshness(db, s.cik) if s.cik else [],
        errors=errors,
        quote=QuoteOut(**q) if q else None,
        key_figures=figures,
        currency=ccy,
        has_financials=bool(facts),
    )


@router.post("/companies/{ticker}/refresh", response_model=CompanyOut)
def refresh(ticker: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    s = get_security(db, ticker)
    if s.cik:
        try:
            fundamentals.refresh_company(db, s.cik, force=True)
        except fundamentals.sec_client.SecError as exc:
            raise HTTPException(400, str(exc))
    return company(ticker, db, user)


@router.get("/companies/{ticker}/financials")
def financials(
    ticker: str,
    statement: str = Query("income", pattern="^(income|balance|cashflow|metrics)$"),
    period: str = Query("annual", pattern="^(annual|quarterly)$"),
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    s = get_security(db, ticker)
    facts = _facts(db, s.cik)
    data = (
        fundamentals.build_metrics(facts, period)
        if statement == "metrics"
        else fundamentals.build_statement(facts, statement, period)
    )
    st = fundamentals.get_state(db, "sec_companyfacts", s.cik) if s.cik else None
    data["source"] = {
        "name": "SEC EDGAR XBRL company facts",
        "url": fundamentals.COMPANYFACTS_URL.format(cik=s.cik) if s.cik else None,
        "last_success_at": st.last_success_at.isoformat() if st and st.last_success_at else None,
    }
    if s.cik:
        for r in data["rows"]:
            for c in r["values"]:
                if c and c.get("accession"):
                    c["url"] = fundamentals.filing_url(s.cik, c["accession"])
    return data


class FilingOut(BaseModel):
    accession: str
    form: str
    filing_date: date
    report_date: date | None
    description: str
    url: str


@router.get("/companies/{ticker}/filings", response_model=list[FilingOut])
def filings(
    ticker: str,
    forms: str = Query("key", max_length=80),
    limit: int = Query(40, ge=1, le=200),
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    s = get_security(db, ticker)
    if not s.cik:
        return []
    stmt = select(Filing).where(Filing.cik == s.cik)
    if forms == "key":
        stmt = stmt.where(Filing.form.in_(KEY_FORMS))
    elif forms != "all":
        stmt = stmt.where(Filing.form.in_([f.strip().upper() for f in forms.split(",") if f.strip()]))
    rows = db.scalars(stmt.order_by(Filing.filing_date.desc()).limit(limit))
    return [
        FilingOut(accession=f.accession, form=f.form, filing_date=f.filing_date, report_date=f.report_date,
                  description=f.description or f.form, url=fundamentals.filing_url(s.cik, f.accession, f.primary_document))
        for f in rows
    ]


# ------------------------------------------------------------------ prices
class BarOut(BaseModel):
    date: date
    open: Decimal | None
    high: Decimal | None
    low: Decimal | None
    close: Decimal
    adj_close: Decimal | None
    volume: int | None


class PricesOut(BaseModel):
    ticker: str
    bars: list[BarOut]
    sources: list[str]
    currency: str | None
    last_date: date | None
    provider_configured: bool
    error: str | None
    note: str


@router.get("/prices/{ticker}", response_model=PricesOut)
def get_prices(
    ticker: str,
    range: str = Query("1y", pattern="^(1m|3m|6m|1y|5y|max)$"),
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    t = ticker.strip().upper()
    err = prices.maybe_refresh(db, t)
    bars = prices.get_bars(db, t, range)
    return PricesOut(
        ticker=t,
        bars=[BarOut(date=b.day, open=b.open, high=b.high, low=b.low, close=b.close, adj_close=b.adj_close, volume=b.volume) for b in bars],
        sources=sorted({b.source for b in bars}),
        currency=bars[-1].currency if bars else None,
        last_date=bars[-1].day if bars else None,
        provider_configured=prices.provider_configured(),
        error=err,
        note="End-of-day closing prices, not real-time. Unadjusted close unless stated.",
    )


class PriceImportIn(BaseModel):
    csv: str = Field(min_length=10, max_length=5_000_000)
    source: str = Field(min_length=2, max_length=48)
    currency: str = Field(min_length=3, max_length=3)

    @field_validator("currency")
    @classmethod
    def _ccy(cls, v: str) -> str:
        if not v.isalpha():
            raise ValueError("Currency must be a 3-letter ISO code")
        return v.upper()


@router.post("/admin/prices/{ticker}/import")
def import_prices(ticker: str, data: PriceImportIn, db: Session = Depends(get_db), _: User = Depends(require_admin)):
    t = ticker.strip().upper()
    if not t or len(t) > 20 or not all(c.isalnum() or c in ".-:" for c in t):
        raise HTTPException(422, "Invalid symbol")
    try:
        bars = prices.parse_csv(data.csv)
    except prices.PriceError as exc:
        raise HTTPException(422, str(exc))
    n = prices.upsert_bars(db, t, bars, source=f"CSV import: {data.source.strip()}", currency=data.currency)
    db.commit()
    alertsvc.evaluate(db, [t])
    return {"ticker": t, "imported": n, "first": bars[0]["day"] if bars else None, "last": max(b["day"] for b in bars)}


@router.get("/admin/prices/status")
def price_status(db: Session = Depends(get_db), _: User = Depends(require_admin)):
    return {"provider": "Tiingo" if prices.provider_configured() else None, "usage": prices.usage(db, prices.TIINGO)}


# ------------------------------------------------------------------ fx
@router.get("/fx")
def fx(db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    row = ecb.sync(db)
    return {
        "base": "EUR",
        "rates": ecb.latest(db),
        "source": "European Central Bank, euro foreign exchange reference rates",
        "source_url": "https://data.ecb.europa.eu/",
        "status": row.status,
        "message": row.message,
        "last_success_at": row.last_success_at,
        "note": "Reference rates for information only (published around 16:00 CET on TARGET working days).",
    }


@router.get("/fx/{ccy}")
def fx_history(ccy: str, db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    ccy = ccy.upper()
    if ccy not in ecb.CURRENCIES:
        raise HTTPException(404, "Currency not tracked")
    return {"base": "EUR", "currency": ccy, "points": ecb.history(db, ccy)}
