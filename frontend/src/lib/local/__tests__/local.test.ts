/* eslint-disable @typescript-eslint/no-explicit-any -- loosely typed API responses in tests */
import { beforeEach, describe, expect, it } from "vitest";
import { ApiError } from "../../errors";
import { handle } from "../api";
import { buildBackup, checkBackup, restoreBackup } from "../backup";
import { DB_NAME, resetDbConnection } from "../db";
import { D, xirr } from "../finance";

const call = <T = any>(method: string, path: string, json?: unknown) => handle(method, path, json) as Promise<T>;
const q = (v: string | null, places = 4) => new D(v!).toFixed(places);

async function fail(method: string, path: string, json?: unknown) {
  try {
    await call(method, path, json);
  } catch (e) {
    expect(e).toBeInstanceOf(ApiError);
    return e as ApiError;
  }
  throw new Error("expected an error");
}

beforeEach(async () => {
  resetDbConnection();
  await new Promise<void>((res) => {
    const r = indexedDB.deleteDatabase(DB_NAME);
    r.onsuccess = r.onerror = r.onblocked = () => res();
  });
});

async function setup(closes: Record<string, number>, symbol = "AAPL") {
  const csv = "Date,Close\n" + Object.entries(closes).map(([d, c]) => `${d},${c}`).join("\n");
  await call("POST", `/api/prices/${symbol}/import`, { csv, source: "test", currency: "USD" });
  return (await call("POST", "/api/portfolios", { name: "R" })).id as number;
}
const tx = (pid: number, kw: Record<string, string>) =>
  call("POST", `/api/portfolios/${pid}/transactions`, { symbol: "AAPL", currency: "USD", quantity: "0", fees: "0", ...kw });
const rets = async (pid: number) => (await call("GET", `/api/portfolios/${pid}/analytics`)).returns.USD;

describe("ledger", () => {
  it("average cost, realised P/L, dividends and market value", async () => {
    const pid = await setup({ "2024-01-02": 100, "2024-01-03": 110 });
    await tx(pid, { kind: "buy", trade_date: "2024-01-02", quantity: "10", price: "100", fees: "10" });
    await tx(pid, { kind: "sell", trade_date: "2024-01-03", quantity: "4", price: "110", fees: "4" });
    await tx(pid, { kind: "dividend", trade_date: "2024-01-03", price: "6", fees: "1" });
    const d = await call("GET", `/api/portfolios/${pid}`);
    const p = d.open_positions[0];
    expect(p.quantity).toBe("6");
    expect(p.cost_basis).toBe("606"); // 1010 - 4 * 101
    expect(p.realized_pl).toBe("32"); // 440 - 4 - 404
    expect(p.dividends).toBe("5");
    expect(p.market_value).toBe("660.00");
    expect(p.unrealized_pl).toBe("54");
    expect(d.totals_by_currency[0].market_value).toBe("660");
  });

  it("refuses a sell beyond holdings and a delete that would cause one", async () => {
    const pid = await setup({ "2024-01-02": 100 });
    await tx(pid, { kind: "buy", trade_date: "2024-01-02", quantity: "1", price: "100" });
    expect((await fail("POST", `/api/portfolios/${pid}/transactions`, { symbol: "AAPL", currency: "USD", kind: "sell", trade_date: "2024-01-03", quantity: "2", price: "1" })).message).toContain("exceeds");
    await tx(pid, { kind: "sell", trade_date: "2024-01-03", quantity: "1", price: "120" });
    const buy = (await call("GET", `/api/portfolios/${pid}`)).transactions.find((t: any) => t.kind === "buy");
    expect((await fail("DELETE", `/api/portfolios/${pid}/transactions/${buy.id}`)).message).toMatch(/^Cannot delete/);
    expect((await fail("POST", `/api/portfolios/${pid}/transactions`, { symbol: "AAPL", currency: "USD", kind: "buy", trade_date: "2999-01-01", quantity: "1", price: "1" })).message).toContain("future");
  });

  it("imports a broker CSV all-or-nothing", async () => {
    const pid = await setup({ "2024-01-02": 600 });
    const good = "Date;Symbol;Type;Quantity;Price;Fees;Currency\n2024-01-02;ASML.AS;Buy;2;600,50;1,50;EUR\n2024-03-01;ASML.AS;Dividend;0;3,20;0;EUR\n";
    expect(await call("POST", `/api/portfolios/${pid}/import`, { csv: good, default_currency: "EUR" })).toEqual({ imported: 2 });
    const badCsv = "Date;Symbol;Type;Quantity;Price\n2024-01-02;X;Buy;1;1,234\n";
    expect((await fail("POST", `/api/portfolios/${pid}/import`, { csv: badCsv })).message).toContain("ambiguous");
    const oversell = "Date,Symbol,Type,Quantity,Price\n2024-01-05,ASML.AS,Sell,5,1\n";
    expect((await fail("POST", `/api/portfolios/${pid}/import`, { csv: oversell, default_currency: "EUR" })).message).toMatch(/^Nothing imported/);
    expect((await call("GET", `/api/portfolios/${pid}`)).transactions).toHaveLength(2);
  });
});

describe("returns (same hand-checked cases as the original server tests)", () => {
  it("TWR ignores deposit timing", async () => {
    const pid = await setup({ "2024-01-02": 100, "2024-01-03": 110, "2024-01-04": 121 });
    await tx(pid, { kind: "buy", trade_date: "2024-01-02", quantity: "10", price: "100" });
    await tx(pid, { kind: "buy", trade_date: "2024-01-03", quantity: "10", price: "110" });
    const r = await rets(pid);
    expect(q(r.twr_total)).toBe("0.2100");
    expect(r.series.map((p: any) => q(p.twr))).toEqual(["0.0000", "0.1000", "0.2100"]);
    expect(r.twr_annualised).toBeNull();
    expect(r.gaps).toBe(0);
  });

  it("fees, dividends and full exit", async () => {
    const pid = await setup({ "2024-01-02": 100, "2024-01-03": 100, "2024-01-04": 100, "2024-01-05": 100 });
    await tx(pid, { kind: "buy", trade_date: "2024-01-02", quantity: "10", price: "100", fees: "10" });
    await tx(pid, { kind: "dividend", trade_date: "2024-01-03", price: "20" });
    await tx(pid, { kind: "sell", trade_date: "2024-01-04", quantity: "10", price: "100", fees: "5" });
    const r = await rets(pid);
    const expected = new D(1000).div(1010).times("1.02").times("0.995").minus(1);
    expect(q(r.twr_total, 6)).toBe(expected.toFixed(6));
    expect(r.series.at(-1).date).toBe("2024-01-04");
  });

  it("skips gaps without inventing values", async () => {
    await call("POST", "/api/prices/MSFT/import", { csv: "Date,Close\n2024-01-02,100\n2024-01-20,110\n", source: "test", currency: "USD" });
    const pid = await setup({ "2024-01-02": 50, "2024-01-12": 60, "2024-01-20": 55 });
    await tx(pid, { kind: "buy", trade_date: "2024-01-02", quantity: "10", price: "50" });
    await tx(pid, { kind: "buy", trade_date: "2024-01-02", symbol: "MSFT", quantity: "5", price: "100" });
    const r = await rets(pid);
    expect(r.gaps).toBe(1);
    expect(r.series.map((p: any) => p.date)).toEqual(["2024-01-02", "2024-01-20"]);
    expect(q(r.twr_total)).toBe("0.1000");
  });

  it("money-weighted differs from time-weighted", async () => {
    const pid = await setup({ "2023-01-02": 100, "2023-07-03": 150, "2024-01-02": 120 });
    await tx(pid, { kind: "buy", trade_date: "2023-01-02", quantity: "1", price: "100" });
    await tx(pid, { kind: "buy", trade_date: "2023-07-03", quantity: "10", price: "150" });
    const r = await rets(pid);
    expect(q(r.twr_total)).toBe("0.2000");
    expect(Number(r.mwr_annualised)).toBeLessThan(0);
    expect(r.twr_annualised).not.toBeNull();
    expect(r.days).toBe(365);
  });

  it("xirr", () => {
    expect(q(xirr([["2023-01-01", new D(-1000)], ["2024-01-01", new D(1100)]]))).toBe("0.1000");
    expect(xirr([["2023-01-01", new D(-1000)]])).toBeNull();
  });
});

describe("allocation with exchange rates", () => {
  it("converts to a base currency only when every rate is stored", async () => {
    const pid = await setup({ "2024-01-02": 100 });
    await tx(pid, { kind: "buy", trade_date: "2024-01-02", quantity: "10", price: "100" });
    let a = (await call("GET", `/api/portfolios/${pid}/analytics?base=EUR`)).allocation;
    expect(a.base.error).toContain("USD");
    await call("PUT", "/api/fx", { currency: "USD", value: "1,25", date: "2024-01-02" });
    a = (await call("GET", `/api/portfolios/${pid}/analytics?base=EUR`)).allocation;
    expect(a.base.total).toBe("800"); // 1000 USD / 1.25
    expect(a.items[0].basis).toBe("market");
  });
});

describe("watchlists, notes, search", () => {
  it("creates a default watchlist, adds any ticker, rejects duplicates", async () => {
    const [wl] = await call("GET", "/api/watchlists");
    expect(wl.name).toBe("My watchlist");
    await call("POST", `/api/watchlists/${wl.id}/items`, { ticker: "asml.as", name: "ASML Holding" });
    expect((await fail("POST", `/api/watchlists/${wl.id}/items`, { ticker: "ASML.AS" })).status).toBe(409);
    expect((await fail("POST", `/api/watchlists/${wl.id}/items`, { ticker: "bad ticker!" })).status).toBe(422);
    const [again] = await call("GET", "/api/watchlists");
    expect(again.items[0].security).toEqual({ ticker: "ASML.AS", name: "ASML Holding", exchange: null });
    expect(again.items[0].quote).toBeNull(); // no price imported: none invented
    await call("DELETE", `/api/watchlists/${wl.id}`);
    expect(await call("GET", "/api/watchlists")).toEqual([]); // not re-created after the user deleted it
  });

  it("notes and search", async () => {
    const n = await call("POST", "/api/notes", { title: "Thesis", body: "Moat is distribution", ticker: "nvo" });
    expect(n.security.ticker).toBe("NVO");
    await call("PUT", `/api/notes/${n.id}`, { title: "Thesis v2", body: "x", ticker: null });
    const hits = await call("GET", "/api/search?q=thesis");
    expect(hits).toEqual([{ type: "note", title: "Thesis v2", subtitle: "Note", href: `/notes?id=${n.id}` }]);
    expect((await fail("GET", "/api/notes/999")).status).toBe(404);
  });
});

describe("backup", () => {
  it("round-trips everything and rejects foreign files", async () => {
    const pid = await setup({ "2024-01-02": 100 });
    await tx(pid, { kind: "buy", trade_date: "2024-01-02", quantity: "3", price: "100" });
    await call("POST", "/api/notes", { title: "Keep me", body: "" });
    await call("PUT", "/api/preferences", { theme: "light", base_currency: "USD" });
    const file = JSON.parse(JSON.stringify(await buildBackup()));
    expect(checkBackup(file)).toMatchObject({ transactions: 1, notes: 1, prices: 1, portfolios: 1 });

    await call("DELETE", `/api/portfolios/${pid}`);
    await call("POST", "/api/notes", { title: "Will be replaced", body: "" });
    await restoreBackup(file);
    expect((await call("GET", "/api/notes")).map((n: any) => n.title)).toEqual(["Keep me"]);
    expect((await call("GET", `/api/portfolios/${pid}`)).open_positions[0].quantity).toBe("3");
    expect((await call("GET", "/api/preferences")).theme).toBe("light");

    expect(() => checkBackup({ app: "other" })).toThrow(/not an Investor Intelligence backup/);
    expect(() => checkBackup({ ...file, version: 99 })).toThrow(/newer version/);
    expect(() => checkBackup({ ...file, data: { ...file.data, notes: [{ nope: 1 }] } })).toThrow(/damaged/);
  });
});
