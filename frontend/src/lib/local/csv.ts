/** Small CSV reader for broker exports: comma, semicolon or tab, quoted fields, header row. */
import { D, todayIso } from "./finance";

export class CsvError extends Error {}

function sniff(sample: string): string {
  const firstLine = sample.split(/\r?\n/, 1)[0] ?? "";
  const counts = [",", ";", "\t"].map((d) => [d, firstLine.split(d).length - 1] as const);
  counts.sort((a, b) => b[1] - a[1]);
  return counts[0][1] > 0 ? counts[0][0] : ",";
}

export function parseCsv(text: string): string[][] {
  const delim = sniff(text.slice(0, 2048));
  const rows: string[][] = [];
  let row: string[] = [];
  let field = "";
  let quoted = false;
  for (let i = 0; i < text.length; i++) {
    const c = text[i];
    if (quoted) {
      if (c === '"') {
        if (text[i + 1] === '"') {
          field += '"';
          i++;
        } else quoted = false;
      } else field += c;
    } else if (c === '"' && field === "") quoted = true;
    else if (c === delim) {
      row.push(field);
      field = "";
    } else if (c === "\n" || c === "\r") {
      if (c === "\r" && text[i + 1] === "\n") i++;
      row.push(field);
      rows.push(row);
      row = [];
      field = "";
    } else field += c;
  }
  if (field !== "" || row.length) {
    row.push(field);
    rows.push(row);
  }
  return rows;
}

export function headerIndex(header: string[], aliases: Record<string, readonly string[]>): Record<string, number | undefined> {
  const h = header.map((x) => x.trim().toLowerCase().replace(/^﻿/, ""));
  return Object.fromEntries(Object.entries(aliases).map(([k, al]) => [k, (() => { const i = h.findIndex((x) => al.includes(x)); return i < 0 ? undefined : i; })()]));
}

/** Accept 1234.5, 1,234.5, 1234,5 and 1.234,5; reject ambiguous 1,234 / 1.234-with-comma style values. */
export function normaliseNumber(raw: string): string {
  const v = raw.replace(/[\s ]/g, "");
  if (!v) return "0";
  if (v.includes(",") && v.includes(".")) {
    return v.lastIndexOf(".") > v.lastIndexOf(",") ? v.replace(/,/g, "") : v.replace(/\./g, "").replace(",", ".");
  }
  if (v.includes(",")) {
    const parts = v.split(",");
    const tail = parts[parts.length - 1];
    const head = parts.slice(0, -1).join(",");
    if (tail.length === 3 && /^-?\d+$/.test(head) && parts.length === 2) {
      throw new CsvError(`ambiguous number '${raw}' (thousands or decimal separator?)`);
    }
    return parts.length === 2 ? v.replace(",", ".") : v.replace(/,/g, "");
  }
  return v;
}

export function isValidDate(d: string): boolean {
  if (!/^\d{4}-\d{2}-\d{2}$/.test(d)) return false;
  const t = new Date(`${d}T00:00:00Z`);
  return !Number.isNaN(t.getTime()) && t.toISOString().slice(0, 10) === d;
}

function dec(v: string | undefined): string | null {
  if (v === undefined || v.trim() === "") return null;
  try {
    const d = new D(v.trim().replace(",", "."));
    return d.isFinite() ? d.toFixed() : null;
  } catch {
    return null;
  }
}

const PRICE_ALIASES = {
  date: ["date", "day", "data", "datum", "time", "timestamp"],
  open: ["open", "otwarcie", "abertura"],
  high: ["high", "najwyzszy", "max"],
  low: ["low", "najnizszy", "min"],
  close: ["close", "zamkniecie", "fecho", "price", "last"],
  adj_close: ["adj close", "adj_close", "adjclose", "adjusted close"],
  volume: ["volume", "wolumen", "vol"],
} as const;

export type ParsedBar = { date: string; open: string | null; high: string | null; low: string | null; close: string; adj_close: string | null; volume: number | null };

/** Daily OHLC CSV with a header row (at least Date and Close). */
export function parsePriceCsv(text: string): ParsedBar[] {
  const rows = parseCsv(text);
  if (!rows.length) throw new CsvError("The file is empty.");
  const cols = headerIndex(rows[0], PRICE_ALIASES);
  if (cols.date === undefined || cols.close === undefined) throw new CsvError("CSV needs a header with at least 'Date' and 'Close' columns.");
  const bars: ParsedBar[] = [];
  let errors = 0;
  for (const row of rows.slice(1)) {
    if (!row.length || row.every((c) => !c.trim())) continue;
    const raw = (row[cols.date] ?? "").trim();
    const date = /^\d{8}$/.test(raw) ? `${raw.slice(0, 4)}-${raw.slice(4, 6)}-${raw.slice(6, 8)}` : raw.slice(0, 10);
    if (!isValidDate(date)) {
      errors++;
      continue;
    }
    const get = (k: keyof typeof PRICE_ALIASES) => (cols[k] !== undefined ? dec(row[cols[k]!]) : null);
    const close = get("close");
    if (close === null || new D(close).lte(0)) {
      errors++;
      continue;
    }
    const vol = get("volume");
    bars.push({ date, open: get("open"), high: get("high"), low: get("low"), close, adj_close: get("adj_close"), volume: vol !== null ? Math.trunc(Number(vol)) : null });
  }
  if (!bars.length) throw new CsvError("No valid rows found in the CSV.");
  if (errors > Math.max(5, Math.floor(bars.length / 10))) throw new CsvError(`${errors} rows could not be parsed. Check the date format (YYYY-MM-DD) and decimals.`);
  if (bars.some((b) => b.date > todayIso())) throw new CsvError("The file contains dates in the future.");
  return bars;
}

export const TX_ALIASES = {
  trade_date: ["date", "trade date", "trade_date", "data", "datum"],
  symbol: ["symbol", "ticker", "isin/ticker", "instrument"],
  kind: ["type", "kind", "action", "side", "transaction"],
  quantity: ["quantity", "qty", "shares", "units"],
  price: ["price", "price per share", "amount", "unit price"],
  fees: ["fees", "fee", "commission", "costs", "tax"],
  currency: ["currency", "ccy"],
  note: ["note", "notes", "comment", "description"],
} as const;

export const KIND_ALIASES: Record<string, "buy" | "sell" | "dividend"> = {
  buy: "buy", b: "buy", purchase: "buy", sell: "sell", s: "sell", sale: "sell", dividend: "dividend", div: "dividend", dividends: "dividend",
};
