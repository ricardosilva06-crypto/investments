"""Discounted cash flow (DCF) valuation.

Pure arithmetic on user-supplied assumptions. Defaults are *suggestions* derived
from reported SEC data and are always labelled as such; the user owns every
assumption. Results are estimates, not facts.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, getcontext

getcontext().prec = 28


class DCFError(ValueError):
    pass


@dataclass
class DCFInputs:
    base_fcf: Decimal  # latest annual free cash flow (currency units)
    growth_stage1: Decimal  # e.g. 0.08
    years_stage1: int  # e.g. 5
    years_stage2: int  # fade years, growth moves linearly from stage1 to terminal
    terminal_growth: Decimal  # e.g. 0.025
    discount_rate: Decimal  # e.g. 0.09
    net_cash: Decimal  # cash + short-term investments − debt (negative = net debt)
    shares: Decimal  # shares outstanding
    price: Decimal | None = None  # stored close, for comparison only


def project(i: DCFInputs) -> list[dict]:
    if i.discount_rate <= i.terminal_growth:
        raise DCFError("The discount rate must be higher than the terminal growth rate.")
    if i.shares <= 0:
        raise DCFError("Shares outstanding must be positive.")
    n = i.years_stage1 + i.years_stage2
    if not 1 <= n <= 30:
        raise DCFError("Projection horizon must be between 1 and 30 years.")
    rows, fcf = [], i.base_fcf
    for t in range(1, n + 1):
        if t <= i.years_stage1:
            g = i.growth_stage1
        else:
            k = t - i.years_stage1
            g = i.growth_stage1 + (i.terminal_growth - i.growth_stage1) * Decimal(k) / Decimal(i.years_stage2 + 1)
        fcf = fcf * (1 + g)
        df = 1 / (1 + i.discount_rate) ** t
        rows.append({"year": t, "growth": g, "fcf": fcf, "discount_factor": df, "pv": fcf * df})
    return rows


def value(i: DCFInputs) -> dict:
    rows = project(i)
    n = len(rows)
    pv_fcf = sum((r["pv"] for r in rows), Decimal(0))
    tv = rows[-1]["fcf"] * (1 + i.terminal_growth) / (i.discount_rate - i.terminal_growth)
    pv_tv = tv * rows[-1]["discount_factor"]
    ev = pv_fcf + pv_tv
    equity = ev + i.net_cash
    per_share = equity / i.shares
    out = {
        "projection": rows,
        "pv_fcf": pv_fcf,
        "terminal_value": tv,
        "pv_terminal": pv_tv,
        "terminal_share": (pv_tv / ev) if ev != 0 else None,
        "enterprise_value": ev,
        "equity_value": equity,
        "per_share": per_share,
        "years": n,
        "upside": (per_share / i.price - 1) if i.price and i.price > 0 else None,
        "implied_multiple": (ev / i.base_fcf) if i.base_fcf > 0 else None,
    }
    return out


def sensitivity(i: DCFInputs) -> dict:
    """Per-share value for discount rate ±2pp and terminal growth ±1pp."""
    rates = [i.discount_rate + Decimal(d) / 100 for d in (-2, -1, 0, 1, 2)]
    growths = [i.terminal_growth + Decimal(d) / 1000 for d in (-10, -5, 0, 5, 10)]
    grid = []
    for r in rates:
        row = []
        for g in growths:
            if r <= g or r <= 0:
                row.append(None)
                continue
            try:
                row.append(value(DCFInputs(**{**i.__dict__, "discount_rate": r, "terminal_growth": g}))["per_share"])
            except DCFError:
                row.append(None)
        grid.append(row)
    return {"discount_rates": rates, "terminal_growths": growths, "per_share": grid}
