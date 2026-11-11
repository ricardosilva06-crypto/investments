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


def value_history(db: Session, txs: list[Transaction]) -> dict[str, list[dict]]:
    """Per currency: daily [{date, value, cost}] where every held symbol has a recent close."""
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
            while ti < len(group) and group[ti].trade_date <= d:
                applied.append(group[ti])
                ti += 1
                changed = True
            if changed:
                led = build_ledger(applied)
                holdings = {p.symbol: p.quantity for p in led.positions.values() if p.quantity > 0}
                cost = sum((p.cost_basis for p in led.positions.values()), Decimal(0))
            if not holdings:
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
                           "cost": cost.quantize(Decimal("0.01"))})
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
