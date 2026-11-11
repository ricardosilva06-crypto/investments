/**
 * Portfolio accounting and analytics, computed on the device from your own transactions
 * and the end-of-day prices you imported. Exact decimal arithmetic (decimal.js).
 *
 * - Ledger: average-cost method (buy fees in cost; sell fees reduce realised P/L).
 * - Value history: a day is valued only when every held symbol has a close within 7 days.
 * - TWR: daily-linked, flows at end of day; XIRR: money-weighted, by bisection.
 */
import DecimalBase from "decimal.js";

export const D = DecimalBase.clone({ precision: 34, rounding: DecimalBase.ROUND_HALF_EVEN, toExpNeg: -40, toExpPos: 40 });
export type Dec = InstanceType<typeof D>;
const ZERO = new D(0);

export type Tx = {
  id: number;
  symbol: string;
  kind: "buy" | "sell" | "dividend";
  trade_date: string; // YYYY-MM-DD
  quantity: string;
  price: string;
  fees: string;
  currency: string;
};
export type Bar = { ticker: string; date: string; close: string; currency: string; source: string };

export class LedgerError extends Error {}

export type Position = {
  symbol: string;
  currency: string;
  quantity: Dec;
  cost_basis: Dec;
  realized_pl: Dec;
  dividends: Dec;
  fees: Dec;
  first_trade: string | null;
  transactions: number;
};

export const avgCost = (p: Position): Dec | null => (p.quantity.gt(0) ? p.cost_basis.div(p.quantity) : null);

/** Plain decimal string without exponent or trailing zeros. */
export const s = (d: Dec): string => {
  const t = d.toFixed();
  return t.includes(".") ? t.replace(/0+$/, "").replace(/\.$/, "") : t;
};
export const s2 = (d: Dec): string => d.toFixed(2);

const q10 = (d: Dec) => d.toDecimalPlaces(10);

function sortTx<T extends Tx>(txs: T[]): T[] {
  return [...txs].sort((a, b) => (a.trade_date < b.trade_date ? -1 : a.trade_date > b.trade_date ? 1 : a.id - b.id));
}

export function buildLedger(transactions: Tx[]): Map<string, Position> {
  const positions = new Map<string, Position>();
  for (const t of sortTx(transactions)) {
    const sym = t.symbol.toUpperCase();
    const ccy = t.currency.toUpperCase();
    const key = `${sym}|${ccy}`;
    let pos = positions.get(key);
    if (!pos) {
      pos = { symbol: sym, currency: ccy, quantity: ZERO, cost_basis: ZERO, realized_pl: ZERO, dividends: ZERO, fees: ZERO, first_trade: null, transactions: 0 };
      positions.set(key, pos);
    }
    const qty = new D(t.quantity), price = new D(t.price), fees = new D(t.fees);
    pos.transactions += 1;
    pos.first_trade ??= t.trade_date;
    pos.fees = pos.fees.plus(fees);
    if (t.kind === "buy") {
      pos.quantity = pos.quantity.plus(qty);
      pos.cost_basis = pos.cost_basis.plus(qty.times(price)).plus(fees);
    } else if (t.kind === "sell") {
      if (qty.gt(pos.quantity)) {
        throw new LedgerError(`Sell of ${s(qty)} ${t.symbol} on ${t.trade_date} exceeds the ${s(pos.quantity)} held at that date`);
      }
      const removed = pos.cost_basis.div(pos.quantity).times(qty);
      pos.realized_pl = pos.realized_pl.plus(qty.times(price)).minus(fees).minus(removed);
      pos.quantity = pos.quantity.minus(qty);
      pos.cost_basis = pos.quantity.isZero() ? ZERO : pos.cost_basis.minus(removed);
    } else if (t.kind === "dividend") {
      // For dividends `price` holds the total cash amount received.
      pos.dividends = pos.dividends.plus(price).minus(fees);
    } else {
      throw new LedgerError(`Unknown transaction kind ${String(t.kind)}`);
    }
  }
  for (const p of positions.values()) {
    p.cost_basis = q10(p.cost_basis);
    p.realized_pl = q10(p.realized_pl);
    p.dividends = q10(p.dividends);
  }
  return positions;
}

// ------------------------------------------------------------------ dates
const dayMs = 86_400_000;
const toUtc = (d: string) => Date.UTC(+d.slice(0, 4), +d.slice(5, 7) - 1, +d.slice(8, 10));
export const daysBetween = (a: string, b: string) => Math.round((toUtc(b) - toUtc(a)) / dayMs);
export const addDays = (d: string, n: number) => new Date(toUtc(d) + n * dayMs).toISOString().slice(0, 10);
export const todayIso = () => {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
};

// ------------------------------------------------------------------ quotes
export type Quote = {
  close: string;
  date: string;
  prev_close: string | null;
  prev_date: string | null;
  change: string | null;
  change_pct: string | null;
  source: string;
  currency: string;
};

/** Last two stored closes per ticker. `bars` may contain any tickers, any order. */
export function latestQuotes(bars: Bar[]): Map<string, Quote> {
  const top = new Map<string, Bar[]>();
  for (const b of bars) {
    const lst = top.get(b.ticker) ?? [];
    lst.push(b);
    lst.sort((x, y) => (x.date < y.date ? 1 : -1));
    if (lst.length > 2) lst.length = 2;
    top.set(b.ticker, lst);
  }
  const out = new Map<string, Quote>();
  for (const [t, [last, prev]] of top) {
    const c = new D(last.close);
    const pc = prev ? new D(prev.close) : null;
    out.set(t, {
      close: last.close,
      date: last.date,
      source: last.source,
      currency: last.currency,
      prev_close: prev?.close ?? null,
      prev_date: prev?.date ?? null,
      change: pc && !pc.isZero() ? s(c.minus(pc)) : null,
      change_pct: pc && !pc.isZero() ? s(c.div(pc).minus(1)) : null,
    });
  }
  return out;
}

// ------------------------------------------------------------------ allocation
/** rates: 1 EUR = x CCY (ECB convention). */
export type FxTable = Map<string, { value: Dec; date: string }>;

export function allocation(txs: Tx[], bars: Bar[], base: string | null, fx: FxTable) {
  const ledger = buildLedger(txs);
  const open = [...ledger.values()].filter((p) => p.quantity.gt(0));
  const quotes = latestQuotes(bars);
  const items = open.map((p) => {
    const qte = quotes.get(p.symbol);
    if (qte && qte.currency === p.currency) {
      return { symbol: p.symbol, currency: p.currency, value: p.quantity.times(qte.close).toDecimalPlaces(2), basis: "market" as const, price_date: qte.date };
    }
    return { symbol: p.symbol, currency: p.currency, value: p.cost_basis, basis: "cost" as const, price_date: null };
  });
  const byCcy = new Map<string, Dec>();
  for (const it of items) byCcy.set(it.currency, (byCcy.get(it.currency) ?? ZERO).plus(it.value));
  items.sort((a, b) => (a.currency < b.currency ? -1 : a.currency > b.currency ? 1 : b.value.cmp(a.value)));
  const outItems = items.map((it) => {
    const tot = byCcy.get(it.currency)!;
    return { ...it, value: s(it.value), weight_in_currency: tot.isZero() ? null : s(it.value.div(tot)) } as Record<string, unknown>;
  });
  let baseOut: Record<string, unknown> | null = null;
  if (base) {
    const need = new Set([...byCcy.keys(), base]);
    need.delete("EUR");
    const missing = [...need].filter((c) => !fx.has(c)).sort();
    if (missing.length) {
      baseOut = { currency: base, error: `No exchange rate stored for ${missing.join(", ")}. Add it in Prices & rates.` };
    } else if (items.length) {
      const rate = (c: string) => (c === "EUR" ? new D(1) : fx.get(c)!.value);
      const conv = (v: Dec, from: string) => v.div(rate(from)).times(rate(base));
      let total = ZERO;
      for (const [c, v] of byCcy) total = total.plus(conv(v, c));
      items.forEach((it, i) => {
        const vb = conv(it.value, it.currency);
        outItems[i].value_base = s(vb);
        outItems[i].weight_total = total.isZero() ? null : s(vb.div(total));
      });
      const dates = [...need].map((c) => fx.get(c)!.date).sort();
      baseOut = {
        currency: base,
        total: s(total),
        rate_date: dates[0] ?? null,
        includes_cost_basis: items.some((i) => i.basis === "cost"),
        note: "Converted with the exchange rates stored on this device (1 EUR = x); not trading rates.",
      };
    }
  }
  return { items: outItems, totals: Object.fromEntries([...byCcy].map(([c, v]) => [c, s(v)])), base: baseOut };
}

// ------------------------------------------------------------------ value history & returns
export const MAX_STALE_DAYS = 7;

function flows(t: Tx): [Dec, Dec] {
  const qty = new D(t.quantity), price = new D(t.price), fees = new D(t.fees);
  if (t.kind === "buy") return [qty.times(price).plus(fees), ZERO];
  if (t.kind === "sell") return [ZERO, qty.times(price).minus(fees)];
  return [ZERO, price.minus(fees)];
}

export type HistPoint = { date: string; value: Dec | null; cost: Dec; inflow: Dec; outflow: Dec };

export function valueHistory(txs: Tx[], bars: Bar[]): Map<string, HistPoint[]> {
  const out = new Map<string, HistPoint[]>();
  const byCcy = new Map<string, Tx[]>();
  for (const t of txs) {
    const c = t.currency.toUpperCase();
    byCcy.set(c, [...(byCcy.get(c) ?? []), t]);
  }
  for (const [ccy, raw] of byCcy) {
    const group = sortTx(raw);
    const symbols = [...new Set(group.map((t) => t.symbol.toUpperCase()))].sort();
    const rel = bars
      .filter((b) => symbols.includes(b.ticker) && b.currency === ccy && b.date >= group[0].trade_date)
      .sort((a, b) => (a.date < b.date ? -1 : 1));
    if (!rel.length) continue;
    const closes = new Map<string, [string, Dec][]>();
    for (const b of rel) closes.set(b.ticker, [...(closes.get(b.ticker) ?? []), [b.date, new D(b.close)]]);
    const days = [...new Set(rel.map((b) => b.date))].sort();
    const idx = new Map(symbols.map((x) => [x, 0]));
    const last = new Map<string, [string, Dec]>();
    const series: HistPoint[] = [];
    const applied: Tx[] = [];
    let ti = 0;
    let cost = ZERO;
    let holdings = new Map<string, Dec>();
    for (const d of days) {
      let changed = false;
      let inflow = ZERO, outflow = ZERO;
      while (ti < group.length && group[ti].trade_date <= d) {
        applied.push(group[ti]);
        const [fi, fo] = flows(group[ti]);
        inflow = inflow.plus(fi);
        outflow = outflow.plus(fo);
        ti++;
        changed = true;
      }
      if (changed) {
        const led = buildLedger(applied);
        holdings = new Map([...led.values()].filter((p) => p.quantity.gt(0)).map((p) => [p.symbol, p.quantity]));
        cost = [...led.values()].reduce((a, p) => a.plus(p.cost_basis), ZERO);
      }
      if (!holdings.size) {
        if (changed && series.length) {
          series.push({ date: d, value: new D("0.00"), cost: cost.toDecimalPlaces(2), inflow, outflow });
        }
        continue;
      }
      for (const sym of symbols) {
        const lst = closes.get(sym) ?? [];
        let i = idx.get(sym)!;
        while (i < lst.length && lst[i][0] <= d) {
          last.set(sym, lst[i]);
          i++;
        }
        idx.set(sym, i);
      }
      let value = ZERO;
      let complete = true;
      for (const [sym, qty] of holdings) {
        const lc = last.get(sym);
        if (!lc || daysBetween(lc[0], d) > MAX_STALE_DAYS) {
          complete = false;
          break;
        }
        value = value.plus(qty.times(lc[1]));
      }
      series.push({ date: d, value: complete ? value.toDecimalPlaces(2) : null, cost: cost.toDecimalPlaces(2), inflow, outflow });
    }
    if (series.some((p) => p.value !== null)) out.set(ccy, series);
  }
  return out;
}

export function timeWeighted(series: HistPoint[]) {
  let growth = new D(1);
  let prev: Dec | null = null;
  let pendIn = ZERO, pendOut = ZERO;
  let gaps = 0;
  let start: string | null = null;
  const points: { date: string; twr: Dec }[] = [];
  for (const p of series) {
    pendIn = pendIn.plus(p.inflow);
    pendOut = pendOut.plus(p.outflow);
    const v = p.value;
    if (v === null) {
      gaps++;
      continue;
    }
    let r: Dec | null = null;
    if (prev !== null && prev.gt(0)) r = v.minus(pendIn).plus(pendOut).div(prev).minus(1);
    else if (pendIn.gt(0)) r = v.plus(pendOut).div(pendIn).minus(1);
    if (r !== null) {
      growth = growth.times(r.plus(1));
      start ??= p.date;
    }
    points.push({ date: p.date, twr: growth.minus(1) });
    prev = v;
    pendIn = ZERO;
    pendOut = ZERO;
  }
  return { start, points, total: start ? growth.minus(1) : null, gaps };
}

function period(points: { date: string; twr: Dec }[], since: string): Dec | null {
  if (!points.length || points[points.length - 1].date < since) return null;
  const base = [...points].reverse().find((p) => p.date < since);
  if (!base) return null;
  return points[points.length - 1].twr.plus(1).div(base.twr.plus(1)).minus(1);
}

/** Annual rate r with Σ cf / (1+r)^(days/365) = 0, by bisection. */
export function xirr(cashflows: [string, Dec][]): string | null {
  if (!cashflows.length || !cashflows.some(([, c]) => c.gt(0)) || !cashflows.some(([, c]) => c.lt(0))) return null;
  const d0 = cashflows.map(([d]) => d).sort()[0];
  const cfs = cashflows.map(([d, c]) => [c.toNumber(), daysBetween(d0, d) / 365] as const);
  if (Math.max(...cfs.map(([, t]) => t)) <= 0) return null;
  const npv = (r: number) => cfs.reduce((a, [c, t]) => a + c / (1 + r) ** t, 0);
  let lo = -0.9999, hi = 10;
  let fLo = npv(lo);
  const fHi = npv(hi);
  if (fLo * fHi > 0) return null;
  for (let i = 0; i < 200; i++) {
    const mid = (lo + hi) / 2;
    const fMid = npv(mid);
    if (Math.abs(fMid) < 1e-9) break;
    if (fLo * fMid < 0) hi = mid;
    else {
      lo = mid;
      fLo = fMid;
    }
  }
  return s(new D(((lo + hi) / 2).toFixed(8)));
}

export function returns(txs: Tx[], bars: Bar[]) {
  const out: Record<string, unknown> = {};
  for (const [ccy, series] of valueHistory(txs, bars)) {
    const tw = timeWeighted(series);
    if (!tw.start || tw.total === null) continue;
    const pts = tw.points;
    const end = pts[pts.length - 1].date;
    const days = daysBetween(tw.start, end);
    const total = tw.total;
    const annual = days >= 365 && total.gt(-1) ? new D(Math.pow(total.plus(1).toNumber(), 365 / days) - 1) : null;
    const lastValue = [...series].reverse().find((p) => p.value !== null)?.value ?? null;
    const cfs: [string, Dec][] = txs
      .filter((t) => t.currency.toUpperCase() === ccy && t.trade_date <= end)
      .map((t) => {
        const [fi, fo] = flows(t);
        return [t.trade_date, fo.minus(fi)] as [string, Dec];
      })
      .filter(([, c]) => !c.isZero());
    if (lastValue && !lastValue.isZero()) cfs.push([end, lastValue]);
    out[ccy] = {
      start: tw.start,
      end,
      days,
      twr_total: s(total),
      twr_annualised: annual ? s(annual) : null,
      twr_ytd: (() => {
        const v = period(pts, `${end.slice(0, 4)}-01-01`);
        return v ? s(v) : null;
      })(),
      twr_1y: (() => {
        const v = period(pts, addDays(end, -365));
        return v ? s(v) : null;
      })(),
      mwr_annualised: xirr(cfs),
      gaps: tw.gaps,
      series: pts.map((p) => ({ date: p.date, twr: p.twr.toFixed(6) })),
    };
  }
  return out;
}

// ------------------------------------------------------------------ dividends
export function dividends(txs: Tx[], today = todayIso()) {
  const ledger = buildLedger(txs);
  const byYear = new Map<string, Map<number, Dec>>();
  const byMonth = new Map<string, Map<string, Dec>>();
  const bySymbol = new Map<string, { symbol: string; currency: string; total: Dec; ttm: Dec; payments: number; last_date: string | null }>();
  const ttmStart = addDays(today, -365);
  for (const t of txs.filter((x) => x.kind === "dividend")) {
    const net = new D(t.price).minus(t.fees);
    const ccy = t.currency.toUpperCase();
    const y = byYear.get(ccy) ?? new Map<number, Dec>();
    const yr = +t.trade_date.slice(0, 4);
    y.set(yr, (y.get(yr) ?? ZERO).plus(net));
    byYear.set(ccy, y);
    if (t.trade_date > ttmStart) {
      const m = byMonth.get(ccy) ?? new Map<string, Dec>();
      const mo = t.trade_date.slice(0, 7);
      m.set(mo, (m.get(mo) ?? ZERO).plus(net));
      byMonth.set(ccy, m);
    }
    const key = `${t.symbol.toUpperCase()}|${ccy}`;
    const e = bySymbol.get(key) ?? { symbol: t.symbol.toUpperCase(), currency: ccy, total: ZERO, ttm: ZERO, payments: 0, last_date: null };
    e.total = e.total.plus(net);
    e.payments++;
    if (t.trade_date > ttmStart) e.ttm = e.ttm.plus(net);
    if (!e.last_date || t.trade_date > e.last_date) e.last_date = t.trade_date;
    bySymbol.set(key, e);
  }
  // Last 12 calendar months, oldest first (same stepping as the original server version).
  const first = `${today.slice(0, 7)}-01`;
  const months = Array.from({ length: 12 }, (_, k) => addDays(first, -31 * (11 - k)).slice(0, 7));
  const symbols = [...bySymbol.entries()].map(([key, e]) => {
    const pos = ledger.get(key);
    const open = pos && pos.quantity.gt(0);
    return {
      symbol: e.symbol,
      currency: e.currency,
      total: s(e.total),
      ttm: s(e.ttm),
      payments: e.payments,
      last_date: e.last_date,
      cost_basis: open ? s(pos.cost_basis) : null,
      yield_on_cost: open && pos.cost_basis.gt(0) && !e.ttm.isZero() ? s(e.ttm.div(pos.cost_basis)) : null,
      _sort: e.total,
    };
  });
  symbols.sort((a, b) => (a.currency < b.currency ? -1 : a.currency > b.currency ? 1 : b._sort.cmp(a._sort)));
  return {
    by_year: Object.fromEntries([...byYear].map(([c, m]) => [c, [...m].sort((a, b) => a[0] - b[0]).map(([year, v]) => ({ year, amount: s(v) }))])),
    ttm_by_currency: Object.fromEntries([...byMonth].map(([c, m]) => [c, s([...m.values()].reduce((a, v) => a.plus(v), ZERO))])),
    last_12_months: Object.fromEntries([...byMonth].map(([c, m]) => [c, months.map((mo) => ({ month: mo, amount: s(m.get(mo) ?? ZERO) }))])),
    by_symbol: symbols.map(({ _sort, ...rest }) => (void _sort, rest)),
    note: "From dividend transactions you recorded (net of withholding/fees). Upcoming dividends are not shown.",
  };
}
