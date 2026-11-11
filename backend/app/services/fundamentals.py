"""Financial statements from SEC XBRL company facts.

Source: https://data.sec.gov/api/xbrl/companyfacts/CIK##########.json (free, official, no key).

Principles
----------
* Values are stored exactly as reported (concept, unit, period, accession, form, filing date).
* When a value was reported more than once for the same period (e.g. restated in a
  later filing), the most recently filed value is used and its filing is cited.
* Each standardised line item lists candidate concepts in priority order; the concept
  actually used is returned with every value.
* Anything not directly reported (e.g. a fourth quarter computed as full year minus
  nine months, or a margin) is marked ``derived`` and carries its formula.
* Missing values stay missing. Nothing is estimated.
"""

from __future__ import annotations

import json
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from ..db import utcnow
from ..models import CompanyProfile, FetchState, FinancialFact, Filing
from . import sec_client

COMPANYFACTS_URL = "https://data.sec.gov/api/xbrl/companyfacts/CIK{cik:010d}.json"
SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik:010d}.json"
FILING_URL = "https://www.sec.gov/Archives/edgar/data/{cik}/{acc}/{doc}"
FILING_INDEX_URL = "https://www.sec.gov/Archives/edgar/data/{cik}/{acc}/"

ANNUAL_FORMS = ("10-K", "10-K/A", "10-KT", "20-F", "20-F/A", "40-F", "40-F/A")
REFRESH_AFTER = timedelta(hours=24)
MIN_RETRY_AFTER_ERROR = timedelta(minutes=15)


# --------------------------------------------------------------------------- items
@dataclass(frozen=True)
class Item:
    key: str
    label: str
    concepts: tuple[str, ...]  # "us-gaap:X" or "ifrs-full:Y"
    kind: str = "money"  # money | per_share | shares
    additive: bool = True  # may quarters be derived by subtraction?
    indent: int = 0


def _c(*names: str) -> tuple[str, ...]:
    return tuple(n if ":" in n else f"us-gaap:{n}" for n in names)


INCOME = [
    Item("revenue", "Revenue", _c("Revenues", "RevenueFromContractWithCustomerExcludingAssessedTax",
         "RevenueFromContractWithCustomerIncludingAssessedTax", "SalesRevenueNet", "SalesRevenueGoodsNet",
         "RevenuesNetOfInterestExpense", "ifrs-full:Revenue")),
    Item("cost_of_revenue", "Cost of revenue", _c("CostOfRevenue", "CostOfGoodsAndServicesSold", "CostOfGoodsSold",
         "CostOfServices", "ifrs-full:CostOfSales"), indent=1),
    Item("gross_profit", "Gross profit", _c("GrossProfit", "ifrs-full:GrossProfit")),
    Item("rnd", "Research & development", _c("ResearchAndDevelopmentExpense",
         "ifrs-full:ResearchAndDevelopmentExpense"), indent=1),
    Item("sga", "Selling, general & admin.", _c("SellingGeneralAndAdministrativeExpense",
         "ifrs-full:SellingGeneralAndAdministrativeExpense"), indent=1),
    Item("operating_income", "Operating income", _c("OperatingIncomeLoss", "ifrs-full:ProfitLossFromOperatingActivities")),
    Item("interest_expense", "Interest expense", _c("InterestExpense", "InterestExpenseNonoperating",
         "ifrs-full:FinanceCosts"), indent=1),
    Item("pretax_income", "Pre-tax income", _c(
        "IncomeLossFromContinuingOperationsBeforeIncomeTaxesExtraordinaryItemsNoncontrollingInterest",
        "IncomeLossFromContinuingOperationsBeforeIncomeTaxesMinorityInterestAndIncomeLossFromEquityMethodInvestments",
        "ifrs-full:ProfitLossBeforeTax")),
    Item("income_tax", "Income tax", _c("IncomeTaxExpenseBenefit", "ifrs-full:IncomeTaxExpenseContinuingOperations"), indent=1),
    Item("net_income", "Net income", _c("NetIncomeLoss", "ProfitLoss", "ifrs-full:ProfitLossAttributableToOwnersOfParent",
         "ifrs-full:ProfitLoss")),
    Item("eps_basic", "EPS (basic)", _c("EarningsPerShareBasic", "ifrs-full:BasicEarningsLossPerShare"),
         kind="per_share", additive=False),
    Item("eps_diluted", "EPS (diluted)", _c("EarningsPerShareDiluted", "ifrs-full:DilutedEarningsLossPerShare"),
         kind="per_share", additive=False),
    Item("shares_diluted", "Diluted shares (weighted)", _c("WeightedAverageNumberOfDilutedSharesOutstanding"),
         kind="shares", additive=False),
    Item("dps", "Dividends declared per share", _c("CommonStockDividendsPerShareDeclared",
         "CommonStockDividendsPerShareCashPaid"), kind="per_share", additive=False),
]

BALANCE = [
    Item("cash", "Cash & equivalents", _c("CashAndCashEquivalentsAtCarryingValue",
         "CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents", "ifrs-full:CashAndCashEquivalents")),
    Item("short_term_investments", "Short-term investments", _c("ShortTermInvestments", "MarketableSecuritiesCurrent",
         "AvailableForSaleSecuritiesDebtSecuritiesCurrent"), indent=1),
    Item("receivables", "Receivables", _c("AccountsReceivableNetCurrent",
         "ifrs-full:TradeAndOtherCurrentReceivables"), indent=1),
    Item("inventory", "Inventory", _c("InventoryNet", "ifrs-full:Inventories"), indent=1),
    Item("current_assets", "Current assets", _c("AssetsCurrent", "ifrs-full:CurrentAssets")),
    Item("total_assets", "Total assets", _c("Assets", "ifrs-full:Assets")),
    Item("accounts_payable", "Accounts payable", _c("AccountsPayableCurrent",
         "ifrs-full:TradeAndOtherCurrentPayables"), indent=1),
    Item("current_liabilities", "Current liabilities", _c("LiabilitiesCurrent", "ifrs-full:CurrentLiabilities")),
    Item("short_term_debt", "Short-term debt", _c("LongTermDebtCurrent", "DebtCurrent", "ShortTermBorrowings",
         "ifrs-full:CurrentBorrowingsAndCurrentPortionOfNoncurrentBorrowings"), indent=1),
    Item("long_term_debt", "Long-term debt", _c("LongTermDebtNoncurrent", "LongTermDebt",
         "ifrs-full:NoncurrentFinancialLiabilities"), indent=1),
    Item("total_liabilities", "Total liabilities", _c("Liabilities", "ifrs-full:Liabilities")),
    Item("equity", "Shareholders' equity", _c("StockholdersEquity",
         "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest",
         "ifrs-full:EquityAttributableToOwnersOfParent", "ifrs-full:Equity")),
    Item("liabilities_and_equity", "Liabilities & equity", _c("LiabilitiesAndStockholdersEquity",
         "ifrs-full:EquityAndLiabilities")),
    Item("shares_outstanding", "Shares outstanding", _c("CommonStockSharesOutstanding"), kind="shares", additive=False),
]

CASHFLOW = [
    Item("cfo", "Operating cash flow", _c("NetCashProvidedByUsedInOperatingActivities",
         "NetCashProvidedByUsedInOperatingActivitiesContinuingOperations",
         "ifrs-full:CashFlowsFromUsedInOperatingActivities")),
    Item("d_and_a", "Depreciation & amortisation", _c("DepreciationDepletionAndAmortization",
         "DepreciationAndAmortization", "DepreciationAmortizationAndAccretionNet",
         "ifrs-full:DepreciationAndAmortisationExpense"), indent=1),
    Item("sbc", "Stock-based compensation", _c("ShareBasedCompensation"), indent=1),
    Item("capex", "Capital expenditure", _c("PaymentsToAcquirePropertyPlantAndEquipment",
         "PaymentsToAcquireProductiveAssets",
         "ifrs-full:PurchaseOfPropertyPlantAndEquipmentClassifiedAsInvestingActivities")),
    Item("cfi", "Investing cash flow", _c("NetCashProvidedByUsedInInvestingActivities",
         "ifrs-full:CashFlowsFromUsedInInvestingActivities")),
    Item("dividends_paid", "Dividends paid", _c("PaymentsOfDividends", "PaymentsOfDividendsCommonStock",
         "ifrs-full:DividendsPaidClassifiedAsFinancingActivities"), indent=1),
    Item("buybacks", "Share repurchases", _c("PaymentsForRepurchaseOfCommonStock"), indent=1),
    Item("cff", "Financing cash flow", _c("NetCashProvidedByUsedInFinancingActivities",
         "ifrs-full:CashFlowsFromUsedInFinancingActivities")),
]

STATEMENTS: dict[str, tuple[list[Item], bool]] = {  # name -> (items, is_instant)
    "income": (INCOME, False),
    "balance": (BALANCE, True),
    "cashflow": (CASHFLOW, False),
}

ALL_CONCEPTS = {c for items, _ in STATEMENTS.values() for i in items for c in i.concepts}


# --------------------------------------------------------------------------- ingest
def _parse_date(v) -> date | None:
    try:
        return date.fromisoformat(v) if v else None
    except (TypeError, ValueError):
        return None


def parse_companyfacts(payload: dict) -> list[dict]:
    """Extract the concepts we use. Rows with unparseable values/dates are skipped."""
    out: list[dict] = []
    facts = payload.get("facts")
    if not isinstance(facts, dict):
        raise sec_client.SecError("Unexpected companyfacts format")
    for taxonomy, concepts in facts.items():
        if not isinstance(concepts, dict):
            continue
        for concept, body in concepts.items():
            if f"{taxonomy}:{concept}" not in ALL_CONCEPTS:
                continue
            for unit, rows in (body.get("units") or {}).items():
                for r in rows:
                    end, filed = _parse_date(r.get("end")), _parse_date(r.get("filed"))
                    if end is None or filed is None or r.get("val") is None:
                        continue
                    try:
                        val = Decimal(str(r["val"]))
                    except (InvalidOperation, ValueError):
                        continue
                    out.append(
                        dict(taxonomy=taxonomy, concept=concept, unit=unit, start=_parse_date(r.get("start")), end=end,
                             value=val, accession=r.get("accn", ""), fy=r.get("fy"), fp=r.get("fp") or "",
                             form=r.get("form") or "", filed=filed, frame=r.get("frame") or "")
                    )
    return out


def parse_submissions(payload: dict) -> tuple[dict, list[dict]]:
    addr = (payload.get("addresses") or {}).get("business") or {}
    address = ", ".join(
        x for x in [addr.get("street1"), addr.get("street2"), addr.get("city"),
                    addr.get("stateOrCountryDescription") or addr.get("stateOrCountry"), addr.get("zipCode")] if x
    )
    profile = dict(
        name=payload.get("name") or "",
        entity_type=payload.get("entityType") or "",
        sic=str(payload.get("sic") or ""),
        sic_description=payload.get("sicDescription") or "",
        category=(payload.get("category") or "").replace("<br>", " · "),
        fiscal_year_end=payload.get("fiscalYearEnd") or "",
        state_of_incorporation=payload.get("stateOfIncorporationDescription") or payload.get("stateOfIncorporation") or "",
        business_address=address,
        phone=payload.get("phone") or "",
        website=payload.get("website") or "",
        investor_website=payload.get("investorWebsite") or "",
        tickers=",".join(payload.get("tickers") or []),
        exchanges=",".join(x for x in (payload.get("exchanges") or []) if x),
        former_names=json.dumps(payload.get("formerNames") or []),
    )
    recent = (payload.get("filings") or {}).get("recent") or {}
    accs = recent.get("accessionNumber") or []
    filings = []
    for i, acc in enumerate(accs):
        def col(name):
            v = recent.get(name) or []
            return v[i] if i < len(v) else None
        fd = _parse_date(col("filingDate"))
        if not acc or fd is None:
            continue
        filings.append(dict(accession=acc, form=col("form") or "", filing_date=fd, report_date=_parse_date(col("reportDate")),
                            primary_document=col("primaryDocument") or "", description=col("primaryDocDescription") or ""))
    return profile, filings


def _state(db: Session, source: str, key: str) -> FetchState:
    st = db.scalar(select(FetchState).where(FetchState.source == source, FetchState.key == key))
    if st is None:
        st = FetchState(source=source, key=key)
        db.add(st)
        db.flush()
    return st


def get_state(db: Session, source: str, cik: int) -> FetchState | None:
    return db.scalar(select(FetchState).where(FetchState.source == source, FetchState.key == str(cik)))


def needs_refresh(st: FetchState | None, force: bool = False) -> bool:
    now = utcnow()
    if st is None or st.last_attempt_at is None:
        return True
    if st.status == "error" and now - st.last_attempt_at < MIN_RETRY_AFTER_ERROR:
        return False
    if force:
        return now - st.last_attempt_at > timedelta(minutes=10)
    return st.last_success_at is None or now - st.last_success_at > REFRESH_AFTER


def refresh_company(db: Session, cik: int, *, force: bool = False) -> dict[str, str]:
    """Download submissions + companyfacts if stale. Returns per-source error messages."""
    errors: dict[str, str] = {}
    for source, url, handler in (
        ("sec_submissions", SUBMISSIONS_URL, _store_submissions),
        ("sec_companyfacts", COMPANYFACTS_URL, _store_facts),
    ):
        st = get_state(db, source, cik)
        if not needs_refresh(st, force):
            if st is not None and st.status == "error":
                errors[source] = st.message
            continue
        st = _state(db, source, str(cik))
        now = utcnow()
        st.last_attempt_at = now
        try:
            payload = sec_client.get_json(url.format(cik=cik))
            handler(db, cik, payload)
            st.status, st.message, st.last_success_at = "ok", "", now
        except sec_client.SecError as exc:
            db.rollback()
            st = _state(db, source, str(cik))
            st.last_attempt_at = now
            st.status = "not_found" if exc.status == 404 else "error"
            st.message = str(exc)
            if st.status == "error":
                errors[source] = str(exc)
        db.commit()
    return errors


def _store_submissions(db: Session, cik: int, payload: dict) -> None:
    profile, filings = parse_submissions(payload)
    row = db.get(CompanyProfile, cik)
    if row is None:
        row = CompanyProfile(cik=cik, **profile)
        db.add(row)
    else:
        for k, v in profile.items():
            setattr(row, k, v)
    row.updated_at = utcnow()
    db.execute(delete(Filing).where(Filing.cik == cik))
    for f in filings:
        db.add(Filing(cik=cik, **f))


def _store_facts(db: Session, cik: int, payload: dict) -> None:
    rows = parse_companyfacts(payload)
    db.execute(delete(FinancialFact).where(FinancialFact.cik == cik))
    db.bulk_insert_mappings(FinancialFact, [dict(cik=cik, **r) for r in rows])


# --------------------------------------------------------------------------- build
@dataclass
class Cell:
    value: Decimal
    concept: str = ""
    unit: str = ""
    accession: str = ""
    form: str = ""
    filed: date | None = None
    derived: bool = False
    formula: str = ""

    def as_dict(self) -> dict:
        return {
            "value": format(self.value, "f"),
            "concept": self.concept,
            "unit": self.unit,
            "accession": self.accession,
            "form": self.form,
            "filed": self.filed.isoformat() if self.filed else None,
            "derived": self.derived,
            "formula": self.formula,
        }


@dataclass
class Period:
    start: date | None
    end: date
    label: str
    fiscal_year_start: date | None = None
    quarter: int | None = None

    def as_dict(self) -> dict:
        return {"start": self.start.isoformat() if self.start else None, "end": self.end.isoformat(), "label": self.label}


@dataclass
class FactIndex:
    """Facts grouped by qualified concept, keeping only the latest-filed value per period."""

    by_concept: dict[str, dict[tuple[date | None, date], FinancialFact]] = field(default_factory=lambda: defaultdict(dict))
    currency: str = "USD"

    @classmethod
    def build(cls, facts: list[FinancialFact]) -> FactIndex:
        idx = cls()
        money_units = defaultdict(int)
        for f in facts:
            if len(f.unit) == 3 and f.unit.isalpha():
                money_units[f.unit] += 1
        if money_units:
            idx.currency = "USD" if "USD" in money_units else max(money_units, key=money_units.get)
        for f in facts:
            if not _unit_ok(f.unit, idx.currency):
                continue
            key = (f.start, f.end)
            q = f"{f.taxonomy}:{f.concept}"
            cur = idx.by_concept[q].get(key)
            if cur is None or (f.filed, f.accession) > (cur.filed, cur.accession):
                idx.by_concept[q][key] = f
        return idx

    def find(self, item: Item, start: date | None, end: date, tolerance_days: int = 0) -> Cell | None:
        for concept in item.concepts:
            periods = self.by_concept.get(concept)
            if not periods:
                continue
            f = periods.get((start, end))
            if f is None and tolerance_days and start is not None:
                for (s, e), cand in periods.items():
                    if e == end and s is not None and abs((s - start).days) <= tolerance_days:
                        f = cand
                        break
            if f is not None:
                return Cell(value=f.value, concept=concept, unit=f.unit, accession=f.accession, form=f.form, filed=f.filed)
        return None


def _unit_ok(unit: str, currency: str) -> bool:
    return unit in (currency, f"{currency}/shares", "shares")


def _days(a: date, b: date) -> int:
    return (b - a).days


def fiscal_years(facts: list[FinancialFact]) -> list[tuple[date, date]]:
    """Annual periods (start, end) reported in annual-report forms, newest first."""
    seen: dict[date, date] = {}
    for f in facts:
        if f.start is None or not f.form.startswith(ANNUAL_FORMS):
            continue
        if 350 <= _days(f.start, f.end) <= 380:
            # Keep one start per end (most common is identical anyway).
            seen.setdefault(f.end, f.start)
    return sorted(((s, e) for e, s in seen.items()), key=lambda p: p[1], reverse=True)


def quarter_ends(facts: list[FinancialFact], fy: tuple[date, date]) -> list[date]:
    """Quarter-end dates within a fiscal year, from year-to-date and 3-month facts."""
    s, e = fy
    ends = {e}
    for f in facts:
        if f.start is None or not (s < f.end < e):
            continue
        d = _days(f.start, f.end)
        if f.start == s and (80 <= d <= 100 or 170 <= d <= 190 or 260 <= d <= 280):
            ends.add(f.end)
    ordered = sorted(ends)
    return ordered if len(ordered) == 4 else []


def _period_label(end: date, quarter: int | None = None) -> str:
    mon = end.strftime("%b %Y")
    return f"Q{quarter} · {mon}" if quarter else f"FY · {mon}"


def build_statement(facts: list[FinancialFact], statement: str, period: str, limit: int | None = None) -> dict:
    items, instant = STATEMENTS[statement]
    idx = FactIndex.build(facts)
    fys = fiscal_years(facts)
    periods: list[Period] = []
    if period == "annual":
        periods = [Period(start=s, end=e, label=_period_label(e)) for s, e in fys[: limit or 10]]
    else:
        for s, e in fys:
            ends = quarter_ends(facts, (s, e))
            for i, qe in enumerate(ends):
                qs = s if i == 0 else ends[i - 1] + timedelta(days=1)
                periods.append(Period(start=qs, end=qe, label=_period_label(qe, i + 1), fiscal_year_start=s, quarter=i + 1))
        periods.sort(key=lambda p: p.end, reverse=True)
        periods = periods[: limit or 12]

    rows = []
    for item in items:
        cells = []
        for p in periods:
            if instant:
                cell = idx.find(item, None, p.end)
            elif period == "annual":
                cell = idx.find(item, p.start, p.end, tolerance_days=7)
            else:
                cell = _quarter_cell(idx, item, p, periods_all=None)
            cells.append(cell.as_dict() if cell else None)
        if any(cells):
            rows.append({"key": item.key, "label": item.label, "kind": item.kind, "indent": item.indent, "values": cells})
    return {
        "statement": statement,
        "period": period,
        "currency": idx.currency,
        "periods": [p.as_dict() for p in periods],
        "rows": rows,
    }


def _quarter_cell(idx: FactIndex, item: Item, p: Period, periods_all=None) -> Cell | None:
    # 1. A directly reported three-month value.
    direct = idx.find(item, p.start, p.end, tolerance_days=7)
    if direct is not None and p.start is not None:
        return direct
    if not item.additive or p.fiscal_year_start is None or p.quarter is None:
        return None
    fy_start = p.fiscal_year_start
    # 2. Year-to-date minus previous year-to-date (both reported).
    ytd = idx.find(item, fy_start, p.end, tolerance_days=7)
    if p.quarter == 1:
        return ytd
    prev_end = p.start - timedelta(days=1)
    prev = idx.find(item, fy_start, prev_end, tolerance_days=7)
    if ytd is None or prev is None:
        return None
    months = {2: ("6", "3"), 3: ("9", "6"), 4: ("12", "9")}[p.quarter]
    return Cell(
        value=ytd.value - prev.value,
        concept=ytd.concept,
        unit=ytd.unit,
        accession=ytd.accession,
        form=ytd.form,
        filed=ytd.filed,
        derived=True,
        formula=f"{months[0]}-month value ({ytd.form} filed {ytd.filed}) minus {months[1]}-month value ({prev.form} filed {prev.filed})",
    )


# --------------------------------------------------------------------------- metrics
def _val(stmt: dict, key: str, i: int) -> Decimal | None:
    for r in stmt["rows"]:
        if r["key"] == key:
            c = r["values"][i]
            return Decimal(c["value"]) if c else None
    return None


def build_metrics(facts: list[FinancialFact], period: str = "annual") -> dict:
    inc = build_statement(facts, "income", period)
    bal = build_statement(facts, "balance", period)
    cf = build_statement(facts, "cashflow", period)
    periods = inc["periods"]
    defs = [
        ("gross_margin", "Gross margin", "percent", "Gross profit ÷ Revenue (Revenue − Cost of revenue if gross profit not reported)"),
        ("operating_margin", "Operating margin", "percent", "Operating income ÷ Revenue"),
        ("net_margin", "Net margin", "percent", "Net income ÷ Revenue"),
        ("fcf", "Free cash flow", "money", "Operating cash flow − Capital expenditure"),
        ("fcf_margin", "FCF margin", "percent", "Free cash flow ÷ Revenue"),
        ("current_ratio", "Current ratio", "ratio", "Current assets ÷ Current liabilities"),
        ("debt_to_equity", "Long-term debt / equity", "ratio", "Long-term debt ÷ Shareholders' equity"),
    ]
    if period == "annual":
        # Not shown for quarters: a quarterly ratio would need annualising (an assumption).
        defs.append(("payout_ratio", "Dividend payout ratio", "percent", "Dividends paid ÷ Net income"))
        defs.insert(5, ("roe", "Return on equity", "percent", "Net income ÷ Shareholders' equity at fiscal year end"))
        defs.insert(0, ("revenue_growth", "Revenue growth (YoY)", "percent", "Revenue ÷ prior fiscal year revenue − 1"))
        defs.insert(1, ("eps_growth", "Diluted EPS growth (YoY)", "percent", "Diluted EPS ÷ prior fiscal year diluted EPS − 1"))

    # Balance sheet periods are matched by end date.
    bal_index = {p["end"]: i for i, p in enumerate(bal["periods"])}
    cf_index = {p["end"]: i for i, p in enumerate(cf["periods"])}

    def div(a, b):
        if a is None or b is None or b == 0:
            return None
        return a / b

    rows = []
    for key, label, kind, formula in defs:
        cells = []
        for i, p in enumerate(periods):
            bi, ci = bal_index.get(p["end"]), cf_index.get(p["end"])
            rev = _val(inc, "revenue", i)
            v = None
            if key == "revenue_growth" and i + 1 < len(periods):
                prev = _val(inc, "revenue", i + 1)
                v = None if div(rev, prev) is None or prev < 0 else div(rev, prev) - 1
            elif key == "eps_growth" and i + 1 < len(periods):
                cur, prev = _val(inc, "eps_diluted", i), _val(inc, "eps_diluted", i + 1)
                v = None if prev is None or prev <= 0 or cur is None else cur / prev - 1
            elif key == "gross_margin":
                gp = _val(inc, "gross_profit", i)
                if gp is None and rev is not None and _val(inc, "cost_of_revenue", i) is not None:
                    gp = rev - _val(inc, "cost_of_revenue", i)
                v = div(gp, rev)
            elif key == "operating_margin":
                v = div(_val(inc, "operating_income", i), rev)
            elif key == "net_margin":
                v = div(_val(inc, "net_income", i), rev)
            elif key in ("fcf", "fcf_margin") and ci is not None:
                cfo, capex = _val(cf, "cfo", ci), _val(cf, "capex", ci)
                fcf = cfo - capex if cfo is not None and capex is not None else None
                v = fcf if key == "fcf" else div(fcf, rev)
            elif key == "roe" and bi is not None:
                eq = _val(bal, "equity", bi)
                v = div(_val(inc, "net_income", i), eq) if eq is not None and eq > 0 else None
            elif key == "payout_ratio" and ci is not None:
                ni = _val(inc, "net_income", i)
                dp = _val(cf, "dividends_paid", ci)
                v = div(dp, ni) if ni is not None and ni > 0 and dp is not None else None
            elif key == "current_ratio" and bi is not None:
                v = div(_val(bal, "current_assets", bi), _val(bal, "current_liabilities", bi))
            elif key == "debt_to_equity" and bi is not None:
                eq = _val(bal, "equity", bi)
                v = div(_val(bal, "long_term_debt", bi), eq) if eq is not None and eq > 0 else None
            cells.append(
                {"value": format(v.quantize(Decimal("0.000001")) if kind != "money" else v, "f"), "derived": True,
                 "formula": formula, "concept": "", "unit": "", "accession": "", "form": "", "filed": None}
                if v is not None else None
            )
        if any(cells):
            rows.append({"key": key, "label": label, "kind": kind, "indent": 0, "values": cells})
    return {"statement": "metrics", "period": period, "currency": inc["currency"], "periods": periods, "rows": rows}


def filing_url(cik: int, accession: str, document: str = "") -> str:
    acc = accession.replace("-", "")
    if document:
        return FILING_URL.format(cik=cik, acc=acc, doc=document)
    return FILING_INDEX_URL.format(cik=cik, acc=acc)
