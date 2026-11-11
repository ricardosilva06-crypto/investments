/**
 * On-device implementation of the app's former REST API.
 * Pages keep calling `api("/api/...")`; requests are answered here from IndexedDB,
 * so the app works without any server and without internet.
 */
import { ApiError } from "../errors";
import { CsvError, KIND_ALIASES, TX_ALIASES, headerIndex, isValidDate, normaliseNumber, parseCsv, parsePriceCsv } from "./csv";
import * as db from "./db";
import type { FxRec, NoteRec, PortfolioRec, PriceRec, SecurityRec, TxRec, WatchItemRec, WatchlistRec } from "./db";
import { D, LedgerError, allocation, avgCost, buildLedger, dividends, latestQuotes, returns, s, todayIso, valueHistory, type Bar, type FxTable } from "./finance";

type Json = Record<string, unknown>;
type Handler = (m: RegExpMatchArray, body: Json, query: URLSearchParams) => Promise<unknown>;

export const TICKER_RE = /^[A-Z0-9.\-:]{1,20}$/;
export const BACKUP_REMINDER_DAYS = 14;
export const DEFAULT_PREFS = { theme: "dark", base_currency: "EUR", compact_numbers: false, display_name: "" };
const MARKET_VALUE_NOTE =
  "Market value uses the latest end-of-day close you imported (date shown), not live prices. Totals are shown only when every open position in that currency has a price; no FX conversion.";

const bad = (msg: string, status = 422) => new ApiError(status, msg);
const notFound = (what: string) => new ApiError(404, `${what} not found`);

function str(body: Json, key: string, { min = 0, max = 200, required = false } = {}): string {
  const v = body[key];
  if (v === undefined || v === null) {
    if (required) throw bad(`${key.replace(/_/g, " ")}: required`);
    return "";
  }
  if (typeof v !== "string") throw bad(`${key.replace(/_/g, " ")}: must be text`);
  const t = v.trim();
  if (t.length < min) throw bad(`${key.replace(/_/g, " ")}: required`);
  if (t.length > max) throw bad(`${key.replace(/_/g, " ")}: at most ${max} characters`);
  return t;
}

export function normTicker(v: unknown): string {
  const t = typeof v === "string" ? v.trim().toUpperCase() : "";
  if (!TICKER_RE.test(t)) throw bad("Ticker may contain letters, digits, '.', '-' or ':' (max 20)");
  return t;
}

function ccy(v: unknown): string {
  const c = typeof v === "string" ? v.trim().toUpperCase() : "";
  if (!/^[A-Z]{3}$/.test(c)) throw bad("Currency must be a 3-letter ISO code");
  return c;
}

function nonNeg(v: unknown, label: string): string {
  const raw = v === undefined || v === null || v === "" ? "0" : String(v);
  let d;
  try {
    d = new D(raw);
  } catch {
    throw bad(`${label}: must be a number`);
  }
  if (!d.isFinite() || d.lt(0)) throw bad(`${label}: must be a non-negative number`);
  return s(d);
}

// ------------------------------------------------------------------ helpers
async function ensureSecurity(ticker: string, name?: string, exchange?: string | null): Promise<SecurityRec> {
  const existing = await db.get<SecurityRec>("securities", ticker);
  if (existing) {
    if ((name && name !== existing.name) || (exchange !== undefined && exchange !== existing.exchange)) {
      const upd = { ...existing, name: name || existing.name, exchange: exchange === undefined ? existing.exchange : exchange };
      await db.put("securities", upd);
      return upd;
    }
    return existing;
  }
  const rec: SecurityRec = { ticker, name: name || ticker, exchange: exchange ?? null, created_at: db.nowIso() };
  await db.put("securities", rec);
  return rec;
}

const secOut = (s: SecurityRec | undefined, ticker: string) => ({ ticker, name: s?.name ?? ticker, exchange: s?.exchange ?? null });

async function securityMap() {
  return new Map((await db.getAll<SecurityRec>("securities")).map((x) => [x.ticker, x]));
}

async function allBars(): Promise<Bar[]> {
  return db.getAll<PriceRec>("prices");
}

async function fxTable(): Promise<FxTable> {
  const t: FxTable = new Map();
  for (const r of await db.getAll<FxRec>("fx")) {
    const cur = t.get(r.currency);
    if (!cur || r.date > cur.date) t.set(r.currency, { value: new D(r.value), date: r.date });
  }
  return t;
}

async function prefs() {
  return { ...DEFAULT_PREFS, ...((await db.kvGet<Json>("preferences")) ?? {}) };
}

async function ownedPortfolio(id: number) {
  const p = await db.get<PortfolioRec>("portfolios", id);
  if (!p) throw notFound("Portfolio");
  return p;
}

const portfolioTxs = (id: number) => db.getByIndex<TxRec>("transactions", "portfolio_id", id);

// ------------------------------------------------------------------ watchlists
async function watchlists() {
  let wls = await db.getAll<WatchlistRec>("watchlists");
  if (!wls.length && !(await db.kvGet("seeded"))) {
    await db.put("watchlists", { name: "My watchlist", created_at: db.nowIso() });
    await db.kvSet("seeded", true);
    wls = await db.getAll<WatchlistRec>("watchlists");
  }
  const items = await db.getAll<WatchItemRec>("watch_items");
  const secs = await securityMap();
  const quotes = latestQuotes(await allBars());
  return wls
    .sort((a, b) => (a.created_at < b.created_at ? -1 : 1))
    .map((w) => ({
      ...w,
      items: items
        .filter((i) => i.watchlist_id === w.id)
        .sort((a, b) => (a.added_at < b.added_at ? -1 : 1))
        .map((i) => ({ id: i.id, note: i.note, added_at: i.added_at, security: secOut(secs.get(i.ticker), i.ticker), quote: quotes.get(i.ticker) ?? null })),
    }));
}

async function ownedWatchlist(id: number) {
  const w = await db.get<WatchlistRec>("watchlists", id);
  if (!w) throw notFound("Watchlist");
  return w;
}

async function ownedItem(wid: number, iid: number) {
  await ownedWatchlist(wid);
  const it = await db.get<WatchItemRec>("watch_items", iid);
  if (!it || it.watchlist_id !== wid) throw notFound("Item");
  return it;
}

// ------------------------------------------------------------------ notes
async function noteOut(n: NoteRec) {
  const sec = n.ticker ? await db.get<SecurityRec>("securities", n.ticker) : undefined;
  return { id: n.id, title: n.title, body: n.body, created_at: n.created_at, updated_at: n.updated_at, security: n.ticker ? secOut(sec, n.ticker) : null };
}

async function noteFields(body: Json) {
  const title = str(body, "title", { min: 1, max: 160, required: true });
  const text = typeof body.body === "string" ? body.body : "";
  if (text.length > 50_000) throw bad("Note is too long (max 50,000 characters)");
  let ticker: string | null = null;
  if (typeof body.ticker === "string" && body.ticker.trim()) {
    ticker = normTicker(body.ticker);
    await ensureSecurity(ticker);
  }
  return { title, body: text, ticker };
}

// ------------------------------------------------------------------ portfolios
function txFields(body: Json, defaults: { currency?: string } = {}): Omit<TxRec, "id" | "portfolio_id" | "created_at"> {
  const symbol = normTicker(body.symbol);
  const kind = body.kind;
  if (kind !== "buy" && kind !== "sell" && kind !== "dividend") throw bad("kind must be buy, sell or dividend");
  const trade_date = typeof body.trade_date === "string" ? body.trade_date.slice(0, 10) : "";
  if (!isValidDate(trade_date)) throw bad("trade date: use YYYY-MM-DD");
  if (trade_date > todayIso()) throw bad("Trade date cannot be in the future");
  const quantity = nonNeg(body.quantity, "quantity");
  const price = nonNeg(body.price, "price");
  const fees = nonNeg(body.fees, "fees");
  if ((kind === "buy" || kind === "sell") && !new D(quantity).gt(0)) throw bad("Quantity must be greater than zero");
  if (kind === "dividend" && !new D(price).gt(0)) throw bad("Dividend amount must be greater than zero");
  const note = typeof body.note === "string" ? body.note.slice(0, 2000) : "";
  return { symbol, kind, trade_date, quantity: kind === "dividend" ? "0" : quantity, price, fees, currency: ccy(body.currency ?? defaults.currency), note };
}

async function portfolioDetail(p: PortfolioRec) {
  const txs = await portfolioTxs(p.id);
  let ledger;
  try {
    ledger = buildLedger(txs);
  } catch (e) {
    throw bad((e as Error).message);
  }
  const secs = await securityMap();
  const quotes = latestQuotes(await allBars());
  const open: Json[] = [], closed: Json[] = [];
  const totals = new Map<string, { currency: string; cost_basis: InstanceType<typeof D>; realized_pl: InstanceType<typeof D>; dividends: InstanceType<typeof D>; market_value: InstanceType<typeof D>; unrealized_pl: InstanceType<typeof D>; priced_positions: number; open_positions: number; oldest_price_date: string | null }>();
  for (const pos of [...ledger.values()].sort((a, b) => (a.symbol < b.symbol ? -1 : 1))) {
    const sec = secs.get(pos.symbol);
    const avg = avgCost(pos);
    const out: Json = {
      symbol: pos.symbol, currency: pos.currency, quantity: s(pos.quantity), average_cost: avg ? s(avg) : null, cost_basis: s(pos.cost_basis),
      realized_pl: s(pos.realized_pl), dividends: s(pos.dividends), fees: s(pos.fees), transactions: pos.transactions, first_trade: pos.first_trade,
      security_ticker: sec ? sec.ticker : null, security_name: sec && sec.name !== sec.ticker ? sec.name : null,
      last_close: null, last_close_date: null, price_source: null, market_value: null, unrealized_pl: null, valuation_note: null,
    };
    let t = totals.get(pos.currency);
    if (!t) {
      t = { currency: pos.currency, cost_basis: new D(0), realized_pl: new D(0), dividends: new D(0), market_value: new D(0), unrealized_pl: new D(0), priced_positions: 0, open_positions: 0, oldest_price_date: null };
      totals.set(pos.currency, t);
    }
    if (pos.quantity.gt(0)) {
      t.open_positions++;
      const q = quotes.get(pos.symbol);
      if (!q) out.valuation_note = "No price imported";
      else if (q.currency !== pos.currency) out.valuation_note = `Price is in ${q.currency}, position in ${pos.currency}; not converted`;
      else {
        const mv = pos.quantity.times(q.close).toDecimalPlaces(2);
        const upl = mv.minus(pos.cost_basis);
        Object.assign(out, { last_close: q.close, last_close_date: q.date, price_source: q.source, market_value: mv.toFixed(2), unrealized_pl: s(upl) });
        t.priced_positions++;
        t.market_value = t.market_value.plus(mv);
        t.unrealized_pl = t.unrealized_pl.plus(upl);
        if (!t.oldest_price_date || q.date < t.oldest_price_date) t.oldest_price_date = q.date;
      }
    }
    (pos.quantity.gt(0) ? open : closed).push(out);
    t.cost_basis = t.cost_basis.plus(pos.cost_basis);
    t.realized_pl = t.realized_pl.plus(pos.realized_pl);
    t.dividends = t.dividends.plus(pos.dividends);
  }
  return {
    portfolio: p,
    open_positions: open,
    closed_positions: closed,
    totals_by_currency: [...totals.values()]
      .sort((a, b) => (a.currency < b.currency ? -1 : 1))
      .map((t) => {
        const complete = t.priced_positions >= t.open_positions && t.open_positions > 0;
        return { ...t, cost_basis: s(t.cost_basis), realized_pl: s(t.realized_pl), dividends: s(t.dividends), market_value: complete ? s(t.market_value) : null, unrealized_pl: complete ? s(t.unrealized_pl) : null };
      }),
    transactions: [...txs].sort((a, b) => (a.trade_date === b.trade_date ? b.id - a.id : a.trade_date < b.trade_date ? 1 : -1)).map((t) => ({ ...t, security_id: null })),
    market_value_note: MARKET_VALUE_NOTE,
  };
}

/** Write transactions only if the resulting ledger is valid (no sell beyond holdings). */
async function addTransactions(pid: number, rows: Omit<TxRec, "id" | "portfolio_id" | "created_at">[], deleteId?: number): Promise<TxRec[]> {
  const existing = await portfolioTxs(pid);
  const now = db.nowIso();
  let tmpId = Math.max(0, ...existing.map((t) => t.id)) + 1;
  const candidate = [...existing.filter((t) => t.id !== deleteId), ...rows.map((r) => ({ ...r, id: tmpId++, portfolio_id: pid, created_at: now }))];
  try {
    buildLedger(candidate);
  } catch (e) {
    if (e instanceof LedgerError) throw bad(deleteId !== undefined ? `Cannot delete: ${e.message}` : e.message);
    throw e;
  }
  const saved: TxRec[] = [];
  await db.atomic(["transactions"], (st) => {
    if (deleteId !== undefined) st("transactions").delete(deleteId);
    for (const r of rows) {
      const rec = { ...r, portfolio_id: pid, created_at: now };
      const req = st("transactions").add(rec);
      req.onsuccess = () => saved.push({ ...rec, id: req.result as number });
    }
  });
  return saved;
}

function importRows(csv: string, defaultCurrency: string) {
  const rows = parseCsv(csv);
  if (!rows.length) throw bad("No transactions found in the file.");
  const cols = headerIndex(rows[0], TX_ALIASES);
  if (["trade_date", "symbol", "kind", "price"].some((k) => cols[k] === undefined)) {
    throw bad("CSV header needs at least: date, symbol, type, price (and quantity for buys/sells).");
  }
  const parsed: ReturnType<typeof txFields>[] = [];
  const errors: string[] = [];
  rows.slice(1).forEach((row, i) => {
    const n = i + 2;
    if (errors.length > 20 || !row.length || row.every((c) => !c.trim())) return;
    const col = (k: string) => (cols[k] !== undefined && cols[k]! < row.length ? row[cols[k]!].trim() : "");
    const kind = KIND_ALIASES[col("kind").toLowerCase()];
    if (!kind) return void errors.push(`line ${n}: unknown type '${col("kind")}'`);
    try {
      parsed.push(txFields({
        symbol: col("symbol"), kind, trade_date: col("trade_date").slice(0, 10), quantity: normaliseNumber(col("quantity")),
        price: normaliseNumber(col("price")), fees: normaliseNumber(col("fees")), currency: col("currency") || defaultCurrency, note: col("note"),
      }));
    } catch (e) {
      errors.push(`line ${n}: ${(e as Error).message}`);
    }
  });
  if (errors.length) throw bad("Nothing imported. " + errors.slice(0, 10).join("; "));
  if (!parsed.length) throw bad("No transactions found in the file.");
  if (parsed.length > 5000) throw bad("Too many rows (max 5000 per import).");
  return parsed;
}

// ------------------------------------------------------------------ routes
const routes: [string, RegExp, Handler][] = [
  ["GET", /^\/api\/preferences$/, async () => prefs()],
  ["PUT", /^\/api\/preferences$/, async (_m, b) => {
    const cur = await prefs();
    const theme = b.theme ?? cur.theme;
    if (!["dark", "light", "system"].includes(String(theme))) throw bad("Unknown theme");
    const next = { theme, base_currency: ccy(b.base_currency ?? cur.base_currency), compact_numbers: !!(b.compact_numbers ?? cur.compact_numbers), display_name: typeof b.display_name === "string" ? b.display_name.trim().slice(0, 40) : cur.display_name };
    await db.kvSet("preferences", next);
    return next;
  }],

  ["GET", /^\/api\/dashboard$/, async () => {
    const wls = await watchlists();
    const items = wls.flatMap((w) => w.items.map((i) => ({ watchlist_id: w.id, watchlist_name: w.name, security: i.security, note: i.note, quote: i.quote })));
    items.sort((a, b) => (a.security.ticker < b.security.ticker ? -1 : 1));
    const notes = (await db.getAll<NoteRec>("notes")).sort((a, b) => (a.updated_at < b.updated_at ? 1 : -1));
    const portfolios = [];
    for (const p of await db.getAll<PortfolioRec>("portfolios")) {
      try {
        const open = [...buildLedger(await portfolioTxs(p.id)).values()].filter((x) => x.quantity.gt(0));
        const by: Record<string, InstanceType<typeof D>> = {};
        for (const x of open) by[x.currency] = (by[x.currency] ?? new D(0)).plus(x.cost_basis);
        portfolios.push({ id: p.id, name: p.name, open_positions: open.length, cost_basis_by_currency: Object.fromEntries(Object.entries(by).map(([k, v]) => [k, s(v)])), error: null });
      } catch (e) {
        portfolios.push({ id: p.id, name: p.name, open_positions: 0, cost_basis_by_currency: {}, error: (e as Error).message });
      }
    }
    const txCount = (await db.getAll("transactions")).length;
    const lastBackup = (await db.kvGet<string>("last_backup_at")) ?? null;
    const hasData = notes.length > 0 || txCount > 0 || items.length > 0;
    const ageDays = lastBackup ? (Date.now() - new Date(lastBackup).getTime()) / 86_400_000 : null;
    return {
      watchlist_count: wls.length,
      watched_securities: new Set(items.map((i) => i.security.ticker)).size,
      watch_items: items.slice(0, 12),
      recent_notes: notes.slice(0, 5).map((n) => ({ id: n.id, title: n.title, updated_at: n.updated_at })),
      note_count: notes.length,
      portfolios,
      last_backup_at: lastBackup,
      has_data: hasData,
      backup_due: hasData && (ageDays === null || ageDays > BACKUP_REMINDER_DAYS),
    };
  }],

  ["GET", /^\/api\/search$/, async (_m, _b, q) => {
    const term = (q.get("q") ?? "").trim().toLowerCase();
    if (!term) return [];
    const hits: Json[] = [];
    for (const w of (await db.getAll<WatchlistRec>("watchlists")).filter((w) => w.name.toLowerCase().includes(term)).slice(0, 3)) {
      hits.push({ type: "watchlist", title: w.name, subtitle: "Watchlist", href: `/watchlist?id=${w.id}` });
    }
    const ports = new Map((await db.getAll<PortfolioRec>("portfolios")).map((p) => [p.id, p.name]));
    const seen = new Set<string>();
    for (const t of await db.getAll<TxRec>("transactions")) {
      const k = `${t.symbol}|${t.portfolio_id}`;
      if (seen.has(k) || !t.symbol.toLowerCase().includes(term) || seen.size >= 5) continue;
      seen.add(k);
      hits.push({ type: "holding", title: t.symbol, subtitle: `In portfolio · ${ports.get(t.portfolio_id) ?? ""}`, href: `/portfolio?id=${t.portfolio_id}` });
    }
    for (const n of (await db.getAll<NoteRec>("notes")).filter((n) => n.title.toLowerCase().includes(term) || n.body.toLowerCase().includes(term)).slice(0, 5)) {
      hits.push({ type: "note", title: n.title, subtitle: "Note", href: `/notes?id=${n.id}` });
    }
    for (const sec of (await db.getAll<SecurityRec>("securities")).filter((x) => x.ticker.toLowerCase().includes(term) || x.name.toLowerCase().includes(term)).slice(0, 15)) {
      hits.push({ type: "security", title: sec.ticker, subtitle: `${sec.name}${sec.exchange ? ` · ${sec.exchange}` : ""}`, href: `/prices?t=${encodeURIComponent(sec.ticker)}` });
    }
    return hits;
  }],

  // securities (your own list: no reference database on the device)
  ["GET", /^\/api\/securities$/, async () => {
    const bars = await allBars();
    const quotes = latestQuotes(bars);
    const counts = new Map<string, number>();
    for (const b of bars) counts.set(b.ticker, (counts.get(b.ticker) ?? 0) + 1);
    return (await db.getAll<SecurityRec>("securities")).sort((a, b) => (a.ticker < b.ticker ? -1 : 1))
      .map((x) => ({ ...secOut(x, x.ticker), quote: quotes.get(x.ticker) ?? null, bars: counts.get(x.ticker) ?? 0 }));
  }],
  ["PUT", /^\/api\/securities\/([^/]+)$/, async (m, b) => {
    const t = normTicker(decodeURIComponent(m[1]));
    const name = str(b, "name", { max: 120 });
    const exchange = str(b, "exchange", { max: 32 }) || null;
    return secOut(await ensureSecurity(t, name || t, exchange), t);
  }],

  // prices
  ["GET", /^\/api\/prices\/([^/]+)$/, async (m) => {
    const t = normTicker(decodeURIComponent(m[1]));
    const bars = (await db.getByIndex<PriceRec>("prices", "ticker", t)).sort((a, b) => (a.date < b.date ? -1 : 1));
    return { ticker: t, bars, sources: [...new Set(bars.map((b) => b.source))].sort(), currency: bars.at(-1)?.currency ?? null, last_date: bars.at(-1)?.date ?? null, note: "End-of-day closing prices you imported. Not real-time." };
  }],
  ["POST", /^\/api\/prices\/([^/]+)\/import$/, async (m, b) => {
    const t = normTicker(decodeURIComponent(m[1]));
    const source = str(b, "source", { min: 2, max: 48, required: true });
    const currency = ccy(b.currency);
    if (typeof b.csv !== "string" || b.csv.length < 10) throw bad("The file is empty.");
    let bars;
    try {
      bars = parsePriceCsv(b.csv);
    } catch (e) {
      if (e instanceof CsvError) throw bad(e.message);
      throw e;
    }
    await ensureSecurity(t);
    const now = db.nowIso();
    await db.atomic(["prices"], (st) => {
      for (const bar of bars) st("prices").put({ ...bar, ticker: t, source: `CSV import: ${source}`, currency, imported_at: now } satisfies PriceRec);
    });
    const dates = bars.map((x) => x.date).sort();
    return { ticker: t, imported: bars.length, first: dates[0], last: dates.at(-1) };
  }],
  ["DELETE", /^\/api\/prices\/([^/]+)$/, async (m) => {
    const t = normTicker(decodeURIComponent(m[1]));
    await db.atomic(["prices"], (st) => {
      st("prices").delete(IDBKeyRange.bound([t, ""], [t, "￿"]));
    });
  }],

  // exchange rates (1 EUR = x CCY)
  ["GET", /^\/api\/fx$/, async () => {
    const table = await fxTable();
    const all = await db.getAll<FxRec>("fx");
    return [...table].sort((a, b) => (a[0] < b[0] ? -1 : 1)).map(([currency, r]) => ({ currency, value: s(r.value), date: r.date, source: all.find((x) => x.currency === currency && x.date === r.date)?.source ?? "" }));
  }],
  ["PUT", /^\/api\/fx$/, async (_m, b) => {
    const currency = ccy(b.currency);
    if (currency === "EUR") throw bad("Rates are per 1 EUR; EUR itself is always 1.");
    const value = nonNeg(typeof b.value === "string" ? normaliseNumber(b.value) : b.value, "rate");
    if (!new D(value).gt(0)) throw bad("rate: must be greater than zero");
    const date = typeof b.date === "string" && isValidDate(b.date) ? b.date : todayIso();
    const source = str(b, "source", { max: 60 }) || "Entered manually";
    await db.put<FxRec>("fx", { currency, date, value, source });
    return { currency, value, date, source };
  }],
  ["DELETE", /^\/api\/fx\/([A-Za-z]{3})$/, async (m) => {
    const c = m[1].toUpperCase();
    await db.atomic(["fx"], (st) => {
      st("fx").delete(IDBKeyRange.bound([c, ""], [c, "￿"]));
    });
  }],

  // watchlists
  ["GET", /^\/api\/watchlists$/, async () => watchlists()],
  ["POST", /^\/api\/watchlists$/, async (_m, b) => {
    const rec = { name: str(b, "name", { min: 1, max: 80, required: true }), created_at: db.nowIso() };
    const id = (await db.put("watchlists", rec)) as number;
    return { id, ...rec, items: [] };
  }],
  ["PATCH", /^\/api\/watchlists\/(\d+)$/, async (m, b) => {
    const w = await ownedWatchlist(+m[1]);
    const upd = { ...w, name: str(b, "name", { min: 1, max: 80, required: true }) };
    await db.put("watchlists", upd);
    return upd;
  }],
  ["DELETE", /^\/api\/watchlists\/(\d+)$/, async (m) => {
    const w = await ownedWatchlist(+m[1]);
    const items = await db.getByIndex<WatchItemRec>("watch_items", "watchlist_id", w.id);
    await db.atomic(["watchlists", "watch_items"], (st) => {
      for (const i of items) st("watch_items").delete(i.id);
      st("watchlists").delete(w.id);
    });
  }],
  ["POST", /^\/api\/watchlists\/(\d+)\/items$/, async (m, b) => {
    const w = await ownedWatchlist(+m[1]);
    const ticker = normTicker(b.ticker);
    const items = await db.getByIndex<WatchItemRec>("watch_items", "watchlist_id", w.id);
    if (items.some((i) => i.ticker === ticker)) throw bad(`${ticker} is already in this watchlist`, 409);
    const sec = await ensureSecurity(ticker, typeof b.name === "string" ? b.name.trim().slice(0, 120) : undefined);
    const rec = { watchlist_id: w.id, ticker, note: typeof b.note === "string" ? b.note.slice(0, 2000) : "", added_at: db.nowIso() };
    const id = (await db.put("watch_items", rec)) as number;
    return { id, note: rec.note, added_at: rec.added_at, security: secOut(sec, ticker), quote: null };
  }],
  ["PATCH", /^\/api\/watchlists\/(\d+)\/items\/(\d+)$/, async (m, b) => {
    const it = await ownedItem(+m[1], +m[2]);
    const note = typeof b.note === "string" ? b.note : "";
    if (note.length > 2000) throw bad("note: at most 2000 characters");
    await db.put("watch_items", { ...it, note });
    return { ...it, note };
  }],
  ["DELETE", /^\/api\/watchlists\/(\d+)\/items\/(\d+)$/, async (m) => {
    const it = await ownedItem(+m[1], +m[2]);
    await db.del("watch_items", it.id);
  }],

  // notes
  ["GET", /^\/api\/notes$/, async (_m, _b, q) => {
    const t = q.get("ticker")?.toUpperCase();
    const notes = (await db.getAll<NoteRec>("notes")).filter((n) => !t || n.ticker === t).sort((a, b) => (a.updated_at < b.updated_at ? 1 : -1));
    return Promise.all(notes.map(noteOut));
  }],
  ["GET", /^\/api\/notes\/(\d+)$/, async (m) => {
    const n = await db.get<NoteRec>("notes", +m[1]);
    if (!n) throw notFound("Note");
    return noteOut(n);
  }],
  ["POST", /^\/api\/notes$/, async (_m, b) => {
    const now = db.nowIso();
    const rec = { ...(await noteFields(b)), created_at: now, updated_at: now };
    const id = (await db.put("notes", rec)) as number;
    return noteOut({ id, ...rec });
  }],
  ["PUT", /^\/api\/notes\/(\d+)$/, async (m, b) => {
    const n = await db.get<NoteRec>("notes", +m[1]);
    if (!n) throw notFound("Note");
    const upd = { ...n, ...(await noteFields(b)), updated_at: db.nowIso() };
    await db.put("notes", upd);
    return noteOut(upd);
  }],
  ["DELETE", /^\/api\/notes\/(\d+)$/, async (m) => {
    if (!(await db.get("notes", +m[1]))) throw notFound("Note");
    await db.del("notes", +m[1]);
  }],

  // portfolios
  ["GET", /^\/api\/portfolios$/, async () => (await db.getAll<PortfolioRec>("portfolios")).sort((a, b) => (a.created_at < b.created_at ? -1 : 1))],
  ["POST", /^\/api\/portfolios$/, async (_m, b) => {
    const rec = { name: str(b, "name", { min: 1, max: 80, required: true }), created_at: db.nowIso() };
    return { id: (await db.put("portfolios", rec)) as number, ...rec };
  }],
  ["GET", /^\/api\/portfolios\/(\d+)$/, async (m) => portfolioDetail(await ownedPortfolio(+m[1]))],
  ["PATCH", /^\/api\/portfolios\/(\d+)$/, async (m, b) => {
    const p = await ownedPortfolio(+m[1]);
    const upd = { ...p, name: str(b, "name", { min: 1, max: 80, required: true }) };
    await db.put("portfolios", upd);
    return upd;
  }],
  ["DELETE", /^\/api\/portfolios\/(\d+)$/, async (m) => {
    const p = await ownedPortfolio(+m[1]);
    const txs = await portfolioTxs(p.id);
    await db.atomic(["portfolios", "transactions"], (st) => {
      for (const t of txs) st("transactions").delete(t.id);
      st("portfolios").delete(p.id);
    });
  }],
  ["POST", /^\/api\/portfolios\/(\d+)\/transactions$/, async (m, b) => {
    const p = await ownedPortfolio(+m[1]);
    const row = txFields(b);
    const [saved] = await addTransactions(p.id, [row]);
    return { ...saved, security_id: null };
  }],
  ["DELETE", /^\/api\/portfolios\/(\d+)\/transactions\/(\d+)$/, async (m) => {
    const p = await ownedPortfolio(+m[1]);
    const t = await db.get<TxRec>("transactions", +m[2]);
    if (!t || t.portfolio_id !== p.id) throw notFound("Transaction");
    await addTransactions(p.id, [], t.id);
  }],
  ["POST", /^\/api\/portfolios\/(\d+)\/import$/, async (m, b) => {
    const p = await ownedPortfolio(+m[1]);
    if (typeof b.csv !== "string" || b.csv.length < 10) throw bad("The file is empty.");
    let rows;
    try {
      rows = importRows(b.csv, typeof b.default_currency === "string" ? b.default_currency : "EUR");
    } catch (e) {
      if (e instanceof CsvError) throw bad(e.message);
      throw e;
    }
    try {
      await addTransactions(p.id, rows);
    } catch (e) {
      if (e instanceof ApiError) throw bad(`Nothing imported: ${e.message}`);
      throw e;
    }
    return { imported: rows.length };
  }],
  ["GET", /^\/api\/portfolios\/(\d+)\/analytics$/, async (m, _b, q) => {
    const p = await ownedPortfolio(+m[1]);
    const txs = await portfolioTxs(p.id);
    const base = q.get("base");
    if (base !== null && !/^[A-Za-z]{3}$/.test(base)) throw bad("base must be a 3-letter currency code");
    const bars = await allBars();
    let alloc;
    try {
      alloc = allocation(txs, bars, base ? base.toUpperCase() : null, await fxTable());
    } catch (e) {
      if (e instanceof LedgerError) throw bad(e.message);
      throw e;
    }
    const hist = valueHistory(txs, bars);
    return {
      allocation: alloc,
      history: Object.fromEntries([...hist].map(([c, pts]) => [c, pts.map((p) => ({ date: p.date, value: p.value ? p.value.toFixed(2) : null, cost: p.cost.toFixed(2), inflow: s(p.inflow), outflow: s(p.outflow) }))])),
      returns: returns(txs, bars),
      returns_note:
        "Time-weighted return (TWR) measures how the investments performed, removing the effect of when you added or withdrew money; it is linked daily from your imported end-of-day closes, with trades valued at their transaction prices and dividends counted as income. Money-weighted return (XIRR) is your own annualised return including the timing of your deposits. Per currency, no FX conversion. Days without a complete valuation are skipped, not estimated.",
      dividends: dividends(txs),
      history_note: "Daily value from your imported end-of-day closes. Days where any held symbol lacks a close within 7 days are left empty.",
    };
  }],
];

export async function handle(method: string, url: string, body: unknown): Promise<unknown> {
  const u = new URL(url, "http://local");
  const path = u.pathname.replace(/\/+$/, "") || "/";
  for (const [m, re, fn] of routes) {
    if (m !== method) continue;
    const match = path.match(re);
    if (match) return fn(match, (body && typeof body === "object" ? body : {}) as Json, u.searchParams);
  }
  throw new ApiError(404, "Not found");
}
