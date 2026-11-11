/**
 * On-device storage (IndexedDB). Everything the app knows lives here, on this phone only.
 * No server, no account: back up with Settings → Export.
 */

export const DB_NAME = "investor-intelligence";
export const DB_VERSION = 1;

export type StoreName =
  | "securities"
  | "watchlists"
  | "watch_items"
  | "notes"
  | "portfolios"
  | "transactions"
  | "prices"
  | "fx"
  | "kv";

export const STORES: { name: StoreName; keyPath: string | string[]; auto?: boolean; indexes?: [string, string][] }[] = [
  { name: "securities", keyPath: "ticker" },
  { name: "watchlists", keyPath: "id", auto: true },
  { name: "watch_items", keyPath: "id", auto: true, indexes: [["watchlist_id", "watchlist_id"]] },
  { name: "notes", keyPath: "id", auto: true },
  { name: "portfolios", keyPath: "id", auto: true },
  { name: "transactions", keyPath: "id", auto: true, indexes: [["portfolio_id", "portfolio_id"]] },
  { name: "prices", keyPath: ["ticker", "date"], indexes: [["ticker", "ticker"]] },
  { name: "fx", keyPath: ["currency", "date"], indexes: [["currency", "currency"]] },
  { name: "kv", keyPath: "key" },
];

export type SecurityRec = { ticker: string; name: string; exchange: string | null; created_at: string };
export type WatchlistRec = { id: number; name: string; created_at: string };
export type WatchItemRec = { id: number; watchlist_id: number; ticker: string; note: string; added_at: string };
export type NoteRec = { id: number; title: string; body: string; ticker: string | null; created_at: string; updated_at: string };
export type PortfolioRec = { id: number; name: string; created_at: string };
export type TxRec = {
  id: number;
  portfolio_id: number;
  symbol: string;
  kind: "buy" | "sell" | "dividend";
  trade_date: string;
  quantity: string;
  price: string;
  fees: string;
  currency: string;
  note: string;
  created_at: string;
};
export type PriceRec = {
  ticker: string;
  date: string;
  open: string | null;
  high: string | null;
  low: string | null;
  close: string;
  adj_close: string | null;
  volume: number | null;
  source: string;
  currency: string;
  imported_at: string;
};
/** 1 EUR = value CCY (same convention as the ECB reference rates). */
export type FxRec = { currency: string; date: string; value: string; source: string };
export type KvRec = { key: string; value: unknown };

let dbPromise: Promise<IDBDatabase> | null = null;

export function openDb(): Promise<IDBDatabase> {
  if (dbPromise) return dbPromise;
  dbPromise = new Promise((resolve, reject) => {
    if (typeof indexedDB === "undefined") {
      reject(new Error("This browser cannot store data on the device (IndexedDB unavailable)."));
      return;
    }
    const req = indexedDB.open(DB_NAME, DB_VERSION);
    req.onupgradeneeded = () => {
      const db = req.result;
      for (const s of STORES) {
        if (db.objectStoreNames.contains(s.name)) continue;
        const os = db.createObjectStore(s.name, { keyPath: s.keyPath, autoIncrement: !!s.auto });
        for (const [name, path] of s.indexes ?? []) os.createIndex(name, path);
      }
    };
    req.onsuccess = () => {
      const db = req.result;
      db.onversionchange = () => {
        db.close();
        dbPromise = null;
      };
      resolve(db);
    };
    req.onerror = () => {
      dbPromise = null;
      reject(req.error ?? new Error("Could not open on-device storage."));
    };
    req.onblocked = () => reject(new Error("Storage is in use by another tab of this app. Close it and try again."));
  });
  return dbPromise;
}

/** For tests: forget the cached connection. */
export function resetDbConnection() {
  dbPromise?.then((d) => d.close()).catch(() => {});
  dbPromise = null;
}

function done<T>(req: IDBRequest<T>): Promise<T> {
  return new Promise((resolve, reject) => {
    req.onsuccess = () => resolve(req.result);
    req.onerror = () => reject(req.error);
  });
}

function txDone(tx: IDBTransaction): Promise<void> {
  return new Promise((resolve, reject) => {
    tx.oncomplete = () => resolve();
    tx.onerror = () => reject(tx.error);
    tx.onabort = () => reject(tx.error ?? new Error("Storage transaction aborted"));
  });
}

export async function getAll<T>(store: StoreName): Promise<T[]> {
  const db = await openDb();
  return done(db.transaction(store).objectStore(store).getAll()) as Promise<T[]>;
}

export async function getByIndex<T>(store: StoreName, index: string, value: IDBValidKey): Promise<T[]> {
  const db = await openDb();
  return done(db.transaction(store).objectStore(store).index(index).getAll(value)) as Promise<T[]>;
}

export async function get<T>(store: StoreName, key: IDBValidKey): Promise<T | undefined> {
  const db = await openDb();
  return done(db.transaction(store).objectStore(store).get(key)) as Promise<T | undefined>;
}

/** Insert or replace. Returns the key (the new id for auto-increment stores). */
export async function put<T>(store: StoreName, value: T): Promise<IDBValidKey> {
  const db = await openDb();
  const tx = db.transaction(store, "readwrite");
  const key = await done(tx.objectStore(store).put(value));
  await txDone(tx);
  return key;
}

export async function del(store: StoreName, key: IDBValidKey | IDBKeyRange): Promise<void> {
  const db = await openDb();
  const tx = db.transaction(store, "readwrite");
  tx.objectStore(store).delete(key);
  await txDone(tx);
}

/** Run several writes atomically: all succeed or none is stored. */
export async function atomic(stores: StoreName[], fn: (s: (name: StoreName) => IDBObjectStore) => void): Promise<void> {
  const db = await openDb();
  const tx = db.transaction(stores, "readwrite");
  try {
    fn((name) => tx.objectStore(name));
  } catch (e) {
    tx.abort();
    throw e;
  }
  await txDone(tx);
}

export async function kvGet<T>(key: string): Promise<T | undefined> {
  const r = await get<KvRec>("kv", key);
  return r?.value as T | undefined;
}

export async function kvSet(key: string, value: unknown): Promise<void> {
  await put<KvRec>("kv", { key, value });
}

export const nowIso = () => new Date().toISOString();
