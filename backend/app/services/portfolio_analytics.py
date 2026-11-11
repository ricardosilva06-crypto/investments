"""Portfolio analytics from the user's own transactions and stored end-of-day closes.

* Allocation: market value where a same-currency close is stored, otherwise cost
  basis (flagged). Per currency; optional conversion to a base currency with ECB
  reference rates (labelled with the rate date).
* Value history: daily value of holdings using stored closes. A day is only valued
  when every held symbol has a close within the previous 7 days; otherwise it is
  left empty rather than guessed.
* Dividends: from recorded dividend transactions only (net of withholding/fees).
"""

from __future__ import annotations

from collections import defaultdict
from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import FxRate, PriceBar, Transaction
from .portfolio import build_ledger
from .prices import latest_quotes

MAX_STALE_DAYS = 7


def fx_rates(db: Session, currencies: set[str]) -> tuple[dict[str, Decimal], date | None, list[str]]:
    """Latest ECB rates as '1 EUR = x CCY'. EUR is 1. Returns (rates, oldest rate date, missing)."""
    rates, dates, missing = {"EUR": Decimal(1)}, [], []
    for c in currencies - {"EUR"}:
        r = db.scalar(select(FxRate).where(FxRate.currency == c).order_by(FxRate.day.desc()).limit(1))
        if r is None:
            missing.append(c)
        else:
            rates[c] = r.value
            dates.append(r.day)
    return rates, (min(dates) if dates else None), missing


def convert(value: Decimal, frm: str, to: str, rates: dict[str, Decimal]) -> Decimal:
    return value / rates[frm] * rates[to]


def allocation(db: Session, txs: list[Transaction], base: str | None) -> dict:
    ledger = build_ledger(txs)
    open_pos = [p for p in ledger.positions.values() if p.quantity > 0]
    quotes = latest_quotes(db, [p.symbol for p in open_pos])
    items = []
    for p in open_pos:
        q = quotes.get(p.symbol)
        if q and q["currency"] == p.currency:
            val, basis, as_of = (p.quantity * q["close"]).quantize(Decimal("0.01")), "market", q["date"]
        else:
            val, basis, as_of = p.cost_basis, "cost", None
        items.append({"symbol": p.symbol, "currency": p.currency, "value": val, "basis": basis, "price_date": as_of})
    by_ccy: dict[str, Decimal] = defaultdict(Decimal)
    for it in items:
        by_ccy[it["currency"]] += it["value"]
    for it in items:
        tot = by_ccy[it["currency"]]
        it["weight_in_currency"] = (it["value"] / tot) if tot else None
    out = {"items": sorted(items, key=lambda x: (x["currency"], -x["value"])), "totals": dict(by_ccy), "base": None}
    if base:
        rates, rate_date, missing = fx_rates(db, set(by_ccy) | {base})
        if missing:
            out["base"] = {"currency": base, "error": f"No ECB rate stored for {', '.join(sorted(missing))}. Open Markets to download rates."}
        elif items:
            total = sum((convert(v, c, base, rates) for c, v in by_ccy.items()), Decimal(0))
            for it in items:
                it["value_base"] = convert(it["value"], it["currency"], base, rates)
                it["weight_total"] = it["value_base"] / total if total else None
            out["base"] = {"currency": base, "total": total, "rate_date": rate_date,
                           "includes_cost_basis": any(i["basis"] == "cost" for i in items),
                           "note": "Converted with ECB euro reference rates; not trading rates."}
    return out


def _flows(t: Transaction) -> tuple[Decimal, Decimal]:
    """(money in, money out) of the holdings for one transaction. Dividends leave the holdings as cash."""
    if t.kind == "buy":
        return t.quantity * t.price + t.fees, Decimal(0)
    if t.kind == "sell":
        return Decimal(0), t.quantity * t.price - t.fees
    return Decimal(0), t.price - t.fees  # dividend (net)


def value_history(db: Session, txs: list[Transaction]) -> dict[str, list[dict]]:
    """Per currency: daily [{date, value, cost, inflow, outflow}] where every held symbol has a recent close.

    ``inflow``/``outflow`` are the cash flows of transactions applied on that day (a transaction on a day
    without a stored close is applied on the next day that has one).
    """
    if not txs:
        return {}
    by_ccy: dict[str, list[Transaction]] = defaultdict(list)
    for t in txs:
        by_ccy[t.currency.upper()].append(t)
    out: dict[str, list[dict]] = {}
    for ccy, group in by_ccy.items():
        group.sort(key=lambda t: (t.trade_date, t.id or 0))
        symbols = sorted({t.symbol.upper() for t in group})
        bars = db.scalars(
            select(PriceBar).where(PriceBar.ticker.in_(symbols), PriceBar.currency == ccy, PriceBar.day >= group[0].trade_date)
            .order_by(PriceBar.day)
        ).all()
        if not bars:
            continue
        closes: dict[str, list[tuple[date, Decimal]]] = defaultdict(list)
        days = sorted({b.day for b in bars})
        for b in bars:
            closes[b.ticker].append((b.day, b.close))
        idx = {s: 0 for s in symbols}
        last: dict[str, tuple[date, Decimal]] = {}
        series, ti, applied = [], 0, []
        cost = Decimal(0)
        holdings: dict[str, Decimal] = {}
        for d in days:
            changed = False
            inflow = outflow = Decimal(0)
            while ti < len(group) and group[ti].trade_date <= d:
                applied.append(group[ti])
                fi, fo = _flows(group[ti])
                inflow, outflow = inflow + fi, outflow + fo
                ti += 1
                changed = True
            if changed:
                led = build_ledger(applied)
                holdings = {p.symbol: p.quantity for p in led.positions.values() if p.quantity > 0}
                cost = sum((p.cost_basis for p in led.positions.values()), Decimal(0))
            if not holdings:
                if changed and series:
                    # Everything was sold (or a dividend arrived after exiting): record the flow at value 0.
                    series.append({"date": d, "value": Decimal("0.00"), "cost": cost.quantize(Decimal("0.01")),
                                   "inflow": inflow, "outflow": outflow})
                continue  # nothing held yet (or a dividend-only record): no value to show
            for s in symbols:
                lst = closes.get(s, [])
                while idx[s] < len(lst) and lst[idx[s]][0] <= d:
                    last[s] = lst[idx[s]]
                    idx[s] += 1
            value, complete = Decimal(0), True
            for s, qty in holdings.items():
                lc = last.get(s)
                if lc is None or (d - lc[0]).days > MAX_STALE_DAYS:
                    complete = False
                    break
                value += qty * lc[1]
            series.append({"date": d, "value": value.quantize(Decimal("0.01")) if complete else None,
                           "cost": cost.quantize(Decimal("0.01")), "inflow": inflow, "outflow": outflow})
        if any(p["value"] is not None for p in series):
            out[ccy] = series
    return out


def dividends(txs: list[Transaction], today: date | None = None) -> dict:
    today = today or date.today()
    ledger = build_ledger(txs)
    divs = [t for t in txs if t.kind == "dividend"]
    by_year: dict[str, dict[int, Decimal]] = defaultdict(lambda: defaultdict(Decimal))
    by_month: dict[str, dict[str, Decimal]] = defaultdict(lambda: defaultdict(Decimal))
    by_symbol: dict[tuple[str, str], dict] = {}
    ttm_start = today - timedelta(days=365)
    for t in divs:
        net = t.price - t.fees
        ccy = t.currency.upper()
        by_year[ccy][t.trade_date.year] += net
        if t.trade_date > ttm_start:
            by_month[ccy][t.trade_date.strftime("%Y-%m")] += net
        key = (t.symbol.upper(), ccy)
        s = by_symbol.setdefault(key, {"symbol": key[0], "currency": ccy, "total": Decimal(0), "ttm": Decimal(0), "payments": 0, "last_date": None})
        s["total"] += net
        s["payments"] += 1
        if t.trade_date > ttm_start:
            s["ttm"] += net
        if s["last_date"] is None or t.trade_date > s["last_date"]:
            s["last_date"] = t.trade_date
    for (sym, ccy), s in by_symbol.items():
        pos = ledger.positions.get((sym, ccy))
        s["cost_basis"] = pos.cost_basis if pos and pos.quantity > 0 else None
        s["yield_on_cost"] = (s["ttm"] / pos.cost_basis) if pos and pos.quantity > 0 and pos.cost_basis > 0 and s["ttm"] else None
    months = [(today.replace(day=1) - timedelta(days=31 * i)).strftime("%Y-%m") for i in range(11, -1, -1)]
    return {
        "by_year": {c: [{"year": y, "amount": v} for y, v in sorted(m.items())] for c, m in by_year.items()},
        "ttm_by_currency": {c: sum(m.values(), Decimal(0)) for c, m in by_month.items()},
        "last_12_months": {c: [{"month": mo, "amount": by_month[c].get(mo, Decimal(0))} for mo in months] for c in by_month},
        "by_symbol": sorted(by_symbol.values(), key=lambda s: (s["currency"], -s["total"])),
        "note": "From dividend transactions you recorded (net of withholding/fees). Upcoming dividends are not shown: no free official source provides them.",
    }


# ------------------------------------------------------------------ returns
def time_weighted(series: list[dict]) -> dict:
    """Daily-linked time-weighted return (TWR) from a value series with cash flows.

    Flows are assumed at the end of the day (GIPS-style daily valuation):
        r_t = (V_t − in_t + out_t) / V_{t−1} − 1
    When nothing was held the day before (V_{t−1} = 0), money comes in at the start of the day:
        r_t = (V_t + out_t) / in_t − 1
    Days without a complete valuation are skipped; their flows carry to the next valued day, so the
    chain stays correct across gaps (the gap count is reported).
    """
    growth = Decimal(1)
    prev: Decimal | None = None
    pend_in = pend_out = Decimal(0)
    gaps = 0
    points: list[dict] = []
    start = None
    for p in series:
        pend_in += p["inflow"]
        pend_out += p["outflow"]
        v = p["value"]
        if v is None:
            gaps += 1
            continue
        if prev is not None and prev > 0:
            r = (v - pend_in + pend_out) / prev - 1
        elif pend_in > 0:
            r = (v + pend_out) / pend_in - 1
        else:
            r = None  # no exposure this day
        if r is not None:
            growth *= 1 + r
            if start is None:
                start = p["date"]
        points.append({"date": p["date"], "twr": growth - 1})
        prev, pend_in, pend_out = v, Decimal(0), Decimal(0)
    return {"start": start, "points": points, "total": growth - 1 if start else None, "gaps": gaps}


def _period(points: list[dict], since: date) -> Decimal | None:
    """TWR between the last point before ``since`` and the latest point."""
    if not points or points[-1]["date"] < since:
        return None
    base = next((p for p in reversed(points) if p["date"] < since), None)
    end = 1 + points[-1]["twr"]
    if base is None:
        return None  # history does not reach back to the start of the period
    return end / (1 + base["twr"]) - 1


def xirr(flows: list[tuple[date, Decimal]]) -> Decimal | None:
    """Money-weighted return: annual rate r with Σ cf_i / (1+r)^(days_i/365) = 0 (bisection)."""
    if not flows or not any(cf > 0 for _, cf in flows) or not any(cf < 0 for _, cf in flows):
        return None
    d0 = min(d for d, _ in flows)
    cfs = [(float(cf), (d - d0).days / 365.0) for d, cf in flows]
    if max(t for _, t in cfs) <= 0:
        return None

    def npv(r: float) -> float:
        return sum(cf / (1 + r) ** t for cf, t in cfs)

    lo, hi = -0.9999, 10.0
    f_lo, f_hi = npv(lo), npv(hi)
    if f_lo * f_hi > 0:
        return None  # no unique solution in a sensible range
    for _ in range(200):
        mid = (lo + hi) / 2
        f_mid = npv(mid)
        if abs(f_mid) < 1e-9:
            break
        if f_lo * f_mid < 0:
            hi, f_hi = mid, f_mid
        else:
            lo, f_lo = mid, f_mid
    return Decimal(str(round((lo + hi) / 2, 8)))


def returns(db: Session, txs: list[Transaction], today: date | None = None) -> dict[str, dict]:
    """Per currency: TWR (total, annualised, YTD, 1Y), money-weighted XIRR and a cumulative TWR series."""
    today = today or date.today()
    out: dict[str, dict] = {}
    for ccy, series in value_history(db, txs).items():
        tw = time_weighted(series)
        if tw["start"] is None:
            continue
        pts = tw["points"]
        end = pts[-1]["date"]
        days = (end - tw["start"]).days
        total = tw["total"]
        annual = (Decimal(str(float(1 + total) ** (365 / days))) - 1) if days >= 365 and total > -1 else None
        last_value = next((p["value"] for p in reversed(series) if p["value"] is not None), None)
        # XIRR on actual trade dates; the final value counts as if sold at the last valued close.
        flows = [(t.trade_date, -_flows(t)[0] + _flows(t)[1]) for t in txs if t.currency.upper() == ccy and t.trade_date <= end]
        flows = [(d, cf) for d, cf in flows if cf != 0]
        if last_value:
            flows.append((end, last_value))
        out[ccy] = {
            "start": tw["start"],
            "end": end,
            "days": days,
            "twr_total": total,
            "twr_annualised": annual,
            "twr_ytd": _period(pts, date(end.year, 1, 1)),
            "twr_1y": _period(pts, end - timedelta(days=365)),
            "mwr_annualised": xirr(flows),
            "gaps": tw["gaps"],
            "series": [{"date": p["date"], "twr": p["twr"].quantize(Decimal("0.000001"))} for p in pts],
        }
    return out
