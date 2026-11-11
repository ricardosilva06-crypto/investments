"""Phase 4 research tools: screener, company comparison, DCF valuation."""

from __future__ import annotations

import json
from datetime import date
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db import get_db
from ..deps import get_current_user, require_admin
from ..models import DataSync, FinancialFact, Security, User, Valuation
from ..services import fundamentals, prices, screener, sec_client
from ..services import valuation as dcf

router = APIRouter(prefix="/api", tags=["research"])


def _sec(db: Session, ticker: str) -> Security:
    s = db.scalar(select(Security).where(Security.ticker == ticker.strip().upper()))
    if s is None:
        raise HTTPException(404, f"Unknown ticker {ticker}")
    return s


def _facts(db: Session, s: Security) -> tuple[list[FinancialFact], dict[str, str]]:
    errors: dict[str, str] = {}
    if not s.cik:
        return [], {"sec": "No SEC CIK for this security"}
    try:
        errors = fundamentals.refresh_company(db, s.cik)
    except sec_client.SecError as exc:
        errors = {"sec": str(exc)}
    return list(db.scalars(select(FinancialFact).where(FinancialFact.cik == s.cik))), errors


def _row(stmt: dict, key: str) -> list[dict | None]:
    return next((r["values"] for r in stmt["rows"] if r["key"] == key), [None] * len(stmt["periods"]))


def _first(stmt: dict, key: str) -> dict | None:
    vals = _row(stmt, key)
    return vals[0] if vals else None


def _d(cell: dict | None) -> Decimal | None:
    return Decimal(cell["value"]) if cell else None


# ------------------------------------------------------------------ screener
@router.get("/screener")
def screen(
    request: Request,
    year: int | None = Query(None, ge=2009, le=2100),
    exchange: str | None = Query(None, max_length=32),
    q: str = Query("", max_length=60),
    sort: str = Query("revenue", max_length=32),
    order: str = Query("desc", pattern="^(asc|desc)$"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    listed_only: bool = True,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    years = screener.available_years(db)
    sync = db.get(DataSync, screener.SOURCE)
    meta = {
        "years": years,
        "metrics": {k: {"label": v[0], "kind": v[1]} for k, v in screener.METRICS.items()},
        "source": "SEC EDGAR XBRL frames (calendar-aligned annual data, USD US-GAAP filers)",
        "last_success_at": sync.last_success_at if sync else None,
        "status": sync.status if sync else "never",
        "message": sync.message if sync else "",
    }
    if not years:
        return {**meta, "year": None, "total": 0, "coverage": 0, "items": []}
    y = year if year in years else years[0]
    rows = screener.compute(db, y)
    coverage = len(rows)

    # Filters: min_<metric>=x / max_<metric>=y (percent metrics as fractions, e.g. 0.1 = 10%).
    filters: list[tuple[str, str, Decimal]] = []
    for k, v in request.query_params.items():
        for prefix in ("min_", "max_"):
            if k.startswith(prefix) and k[4:] in screener.METRICS and v != "":
                try:
                    filters.append((k[4:], prefix[:3], Decimal(v)))
                except ArithmeticError:
                    raise HTTPException(422, f"Invalid number for {k}")
    term = q.strip().lower()

    def keep(r: screener.Row) -> bool:
        if listed_only and not r.ticker:
            return False
        if exchange and r.exchange != exchange:
            return False
        if term and term not in r.name.lower() and term != (r.ticker or "").lower():
            return False
        for metric, op, bound in filters:
            val = r.values.get(metric)
            if val is None:
                return False  # unknown values never pass a filter
            if (op == "min" and val < bound) or (op == "max" and val > bound):
                return False
        return True

    out = [r for r in rows if keep(r)]
    if sort not in screener.METRICS:
        raise HTTPException(422, "Unknown sort metric")
    with_val = [r for r in out if r.values.get(sort) is not None]
    without = [r for r in out if r.values.get(sort) is None]
    with_val.sort(key=lambda r: r.values[sort], reverse=order == "desc")
    out = with_val + without  # missing values always last
    page = out[offset : offset + limit]
    return {
        **meta,
        "year": y,
        "total": len(out),
        "coverage": coverage,
        "items": [
            {"cik": r.cik, "ticker": r.ticker, "name": r.name, "exchange": r.exchange,
             "period_end": r.period_end, "values": {k: (format(v, "f") if v is not None else None) for k, v in r.values.items()}}
            for r in page
        ],
    }


@router.post("/admin/screener/sync")
def sync_screener(year: int | None = Query(None, ge=2009, le=2100), db: Session = Depends(get_db), _: User = Depends(require_admin)):
    row = screener.sync(db, year)
    if row.status == "error":
        raise HTTPException(400, row.message)
    return {"status": row.status, "records": row.record_count, "message": row.message}


# ------------------------------------------------------------------ compare
COMPARE_FIELDS = [
    ("revenue", "income", "Revenue", "money"),
    ("revenue_growth", "metrics", "Revenue growth", "percent"),
    ("gross_margin", "metrics", "Gross margin", "percent"),
    ("operating_margin", "metrics", "Operating margin", "percent"),
    ("net_income", "income", "Net income", "money"),
    ("net_margin", "metrics", "Net margin", "percent"),
    ("eps_diluted", "income", "EPS (diluted)", "per_share"),
    ("eps_growth", "metrics", "EPS growth", "percent"),
    ("fcf", "metrics", "Free cash flow", "money"),
    ("fcf_margin", "metrics", "FCF margin", "percent"),
    ("roe", "metrics", "Return on equity", "percent"),
    ("debt_to_equity", "metrics", "LT debt / equity", "ratio"),
    ("current_ratio", "metrics", "Current ratio", "ratio"),
    ("dps", "income", "Dividend per share", "per_share"),
    ("payout_ratio", "metrics", "Payout ratio", "percent"),
]


@router.get("/compare")
def compare(tickers: str = Query(..., max_length=80), db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    syms = [t.strip().upper() for t in tickers.split(",") if t.strip()]
    syms = list(dict.fromkeys(syms))
    if not 2 <= len(syms) <= 3:
        raise HTTPException(422, "Compare 2 or 3 companies")
    companies = []
    for t in syms:
        s = _sec(db, t)
        facts, errors = _facts(db, s)
        stmts = {
            "income": fundamentals.build_statement(facts, "income", "annual", limit=6),
            "cashflow": fundamentals.build_statement(facts, "cashflow", "annual", limit=6),
            "metrics": fundamentals.build_metrics(facts, "annual"),
        } if facts else {}
        fields = {}
        for key, st, _label, _kind in COMPARE_FIELDS:
            cell = _first(stmts[st], key) if stmts else None
            fields[key] = cell
        q = prices.latest_quotes(db, [s.ticker]).get(s.ticker)
        eps = _d(fields.get("eps_diluted"))
        ccy = stmts["income"]["currency"] if stmts else None
        pe = (q["close"] / eps) if q and eps and eps > 0 and q["currency"] == ccy else None
        history = []
        if stmts:
            inc, cf, met = stmts["income"], stmts["cashflow"], stmts["metrics"]
            fcf_by_end = {p["end"]: v for p, v in zip(met["periods"], _row(met, "fcf"))}
            for p, rev, ni in zip(inc["periods"], _row(inc, "revenue"), _row(inc, "net_income")):
                history.append({"end": p["end"], "revenue": rev["value"] if rev else None,
                                "net_income": ni["value"] if ni else None,
                                "fcf": fcf_by_end.get(p["end"])["value"] if fcf_by_end.get(p["end"]) else None})
            history.reverse()
        companies.append({
            "ticker": s.ticker,
            "name": s.name,
            "currency": ccy,
            "fiscal_year_end": stmts["income"]["periods"][0]["end"] if stmts and stmts["income"]["periods"] else None,
            "fields": fields,
            "quote": {"close": format(q["close"], "f"), "date": q["date"], "source": q["source"], "currency": q["currency"]} if q else None,
            "pe": format(pe.quantize(Decimal("0.01")), "f") if pe else None,
            "history": history,
            "errors": errors,
        })
    return {"fields": [{"key": k, "label": l, "kind": kind} for k, _s, l, kind in COMPARE_FIELDS], "companies": companies}


# ------------------------------------------------------------------ DCF
def _field(value, label: str, kind: str, source: str = "", **extra) -> dict:
    return {"value": format(value, "f") if isinstance(value, Decimal) else value, "label": label, "kind": kind, "source": source, **extra}


@router.get("/companies/{ticker}/dcf-inputs")
def dcf_inputs(ticker: str, db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    s = _sec(db, ticker)
    facts, errors = _facts(db, s)
    if not facts:
        raise HTTPException(404, "No SEC financial data available for this company, so a DCF cannot be pre-filled.")
    inc = fundamentals.build_statement(facts, "income", "annual", limit=6)
    cf = fundamentals.build_statement(facts, "cashflow", "annual", limit=6)
    bal = fundamentals.build_statement(facts, "balance", "annual", limit=1)
    ccy = inc["currency"]
    out: dict = {"ticker": s.ticker, "name": s.name, "currency": ccy, "errors": errors, "fields": {}, "history": []}

    cfo_row, capex_row = _row(cf, "cfo"), _row(cf, "capex")
    for p, cfo, capex in zip(cf["periods"], cfo_row, capex_row):
        if cfo and capex:
            out["history"].append({"end": p["end"], "fcf": format(Decimal(cfo["value"]) - Decimal(capex["value"]), "f"),
                                   "cfo": cfo["value"], "capex": capex["value"]})
    if not out["history"]:
        raise HTTPException(404, "Operating cash flow and capital expenditure are not both reported, so free cash flow cannot be computed.")
    latest = out["history"][0]
    out["fields"]["base_fcf"] = _field(Decimal(latest["fcf"]), "Base free cash flow", "calculated",
                                        f"Operating cash flow − capex, fiscal year ended {latest['end']} (SEC XBRL)")

    revs = [(p["end"], Decimal(c["value"])) for p, c in zip(inc["periods"], _row(inc, "revenue")) if c]
    growth, gsrc = Decimal("0.05"), "Default assumption (no 3-year revenue history)"
    if len(revs) >= 4 and revs[3][1] > 0 and revs[0][1] > 0:
        cagr = Decimal(float(revs[0][1] / revs[3][1]) ** (1 / 3) - 1)
        growth = max(Decimal("-0.05"), min(Decimal("0.15"), cagr)).quantize(Decimal("0.005"))
        gsrc = f"Suggested from 3-year revenue CAGR {float(cagr) * 100:.1f}% ({revs[3][0]} → {revs[0][0]}), capped to −5%…15%"
    out["fields"]["growth_stage1"] = _field(growth, "Growth, years 1–5", "assumption", gsrc)
    out["fields"]["years_stage1"] = _field(5, "High-growth years", "assumption", "Default assumption")
    out["fields"]["years_stage2"] = _field(5, "Fade years (to terminal growth)", "assumption", "Default assumption")
    out["fields"]["terminal_growth"] = _field(Decimal("0.025"), "Terminal growth", "assumption", "Default assumption (≈ long-run inflation + real growth)")
    out["fields"]["discount_rate"] = _field(Decimal("0.09"), "Discount rate", "assumption", "Default assumption (typical equity cost of capital); adjust for risk")

    def b(key):
        c = _first(bal, key)
        return (Decimal(c["value"]), c) if c else (Decimal(0), None)

    cash, c1 = b("cash")
    sti, c2 = b("short_term_investments")
    ltd, c3 = b("long_term_debt")
    std, c4 = b("short_term_debt")
    parts = [f"{lbl} {('reported' if c else 'not reported → 0')}" for lbl, c in
             (("cash", c1), ("short-term investments", c2), ("long-term debt", c3), ("short-term debt", c4))]
    end = bal["periods"][0]["end"] if bal["periods"] else "n/a"
    out["fields"]["net_cash"] = _field(cash + sti - ltd - std, "Net cash (− = net debt)", "calculated",
                                       f"Cash + short-term investments − long-term debt − short-term debt at {end}: " + ", ".join(parts)
                                       + ". Leases and other obligations are not included.")
    sh = _first(bal, "shares_outstanding")
    if sh:
        out["fields"]["shares"] = _field(Decimal(sh["value"]), "Shares outstanding", "reported", f"{sh['concept']}, {sh['form']} filed {sh['filed']}")
    else:
        dil = _first(inc, "shares_diluted")
        if dil:
            out["fields"]["shares"] = _field(Decimal(dil["value"]), "Shares outstanding", "reported",
                                             f"Weighted diluted shares for the latest fiscal year ({dil['concept']}); period-end count not reported")
        else:
            out["fields"]["shares"] = _field(None, "Shares outstanding", "missing", "Not reported in XBRL; enter it manually")
    q = prices.latest_quotes(db, [s.ticker]).get(s.ticker)
    out["price"] = ({"close": format(q["close"], "f"), "date": q["date"], "source": q["source"]} if q and q["currency"] == ccy else None)
    return out


class DCFIn(BaseModel):
    base_fcf: Decimal
    growth_stage1: Decimal = Field(ge=Decimal("-0.5"), le=Decimal("1"))
    years_stage1: int = Field(ge=0, le=20)
    years_stage2: int = Field(ge=0, le=20)
    terminal_growth: Decimal = Field(ge=Decimal("-0.05"), le=Decimal("0.1"))
    discount_rate: Decimal = Field(gt=0, le=Decimal("0.5"))
    net_cash: Decimal
    shares: Decimal = Field(gt=0)
    price: Decimal | None = Field(None, gt=0)


def _fmt(obj):
    if isinstance(obj, Decimal):
        return format(obj.quantize(Decimal("0.000001")) if abs(obj) < 1000 else obj.quantize(Decimal("1")), "f")
    if isinstance(obj, list):
        return [_fmt(x) for x in obj]
    if isinstance(obj, dict):
        return {k: _fmt(v) for k, v in obj.items()}
    return obj


@router.post("/valuation/dcf")
def run_dcf(data: DCFIn, _: User = Depends(get_current_user)):
    inp = dcf.DCFInputs(**data.model_dump())
    try:
        res = dcf.value(inp)
        sens = dcf.sensitivity(inp)
    except dcf.DCFError as exc:
        raise HTTPException(422, str(exc))
    if data.base_fcf <= 0:
        res["warning"] = "Base free cash flow is zero or negative; a simple DCF is not meaningful for this company."
    return _fmt({"result": res, "sensitivity": sens})


class SaveValuationIn(BaseModel):
    ticker: str = Field(min_length=1, max_length=20)
    name: str = Field("", max_length=120)
    inputs: DCFIn


@router.get("/valuations")
def list_valuations(ticker: str | None = Query(None, max_length=20), db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    stmt = select(Valuation).where(Valuation.user_id == user.id)
    if ticker:
        stmt = stmt.where(Valuation.ticker == ticker.upper())
    return [
        {"id": v.id, "ticker": v.ticker, "name": v.name, "inputs": json.loads(v.inputs), "summary": json.loads(v.summary),
         "created_at": v.created_at}
        for v in db.scalars(stmt.order_by(Valuation.created_at.desc()).limit(100))
    ]


@router.post("/valuations", status_code=201)
def save_valuation(data: SaveValuationIn, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    s = _sec(db, data.ticker)
    try:
        res = dcf.value(dcf.DCFInputs(**data.inputs.model_dump()))
    except dcf.DCFError as exc:
        raise HTTPException(422, str(exc))
    summary = _fmt({k: res[k] for k in ("enterprise_value", "equity_value", "per_share", "terminal_share", "upside")})
    v = Valuation(user_id=user.id, ticker=s.ticker, name=data.name.strip() or f"DCF {date.today().isoformat()}",
                  inputs=json.dumps(_fmt(data.inputs.model_dump())), summary=json.dumps(summary))
    db.add(v)
    db.commit()
    return {"id": v.id}


@router.delete("/valuations/{vid}", status_code=204)
def delete_valuation(vid: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    v = db.scalar(select(Valuation).where(Valuation.id == vid, Valuation.user_id == user.id))
    if v is None:
        raise HTTPException(404, "Valuation not found")
    db.delete(v)
    db.commit()

