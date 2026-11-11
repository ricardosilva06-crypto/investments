/** Backup of everything stored on the device, as one JSON file you keep (e.g. in iCloud Drive). */
import { STORES, atomic, getAll, kvGet, kvSet, nowIso, type StoreName } from "./db";

export const BACKUP_APP = "investor-intelligence";
export const BACKUP_VERSION = 1;
const DATA_STORES = STORES.map((s) => s.name).filter((n) => n !== "kv") as StoreName[];
// Settings that travel with a backup; device-only flags (like the last backup date) do not.
const KV_KEYS = ["preferences", "seeded"];

export type Backup = { app: string; version: number; exported_at: string; data: Partial<Record<StoreName, unknown[]>> };

export async function buildBackup(): Promise<Backup> {
  const data: Backup["data"] = {};
  for (const s of DATA_STORES) data[s] = await getAll(s);
  data.kv = (await getAll<{ key: string }>("kv")).filter((r) => KV_KEYS.includes(r.key));
  return { app: BACKUP_APP, version: BACKUP_VERSION, exported_at: nowIso(), data };
}

export function backupFileName(d = new Date()) {
  const p = (n: number) => String(n).padStart(2, "0");
  return `investor-backup-${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}.json`;
}

export async function markBackedUp() {
  await kvSet("last_backup_at", nowIso());
}

export const lastBackupAt = () => kvGet<string>("last_backup_at");

const REQUIRED: Partial<Record<StoreName, string[]>> = {
  securities: ["ticker", "name"],
  watchlists: ["id", "name"],
  watch_items: ["id", "watchlist_id", "ticker"],
  notes: ["id", "title", "body"],
  portfolios: ["id", "name"],
  transactions: ["id", "portfolio_id", "symbol", "kind", "trade_date", "quantity", "price", "fees", "currency"],
  prices: ["ticker", "date", "close", "currency"],
  fx: ["currency", "date", "value"],
  kv: ["key"],
};

/** Validate a parsed backup file; returns per-store counts. Throws with a readable message. */
export function checkBackup(raw: unknown): Record<string, number> {
  if (!raw || typeof raw !== "object") throw new Error("This is not a backup file.");
  const b = raw as Backup;
  if (b.app !== BACKUP_APP) throw new Error("This file is not an Investor Intelligence backup.");
  if (typeof b.version !== "number" || b.version > BACKUP_VERSION) throw new Error("This backup was made by a newer version of the app. Update the app first.");
  if (!b.data || typeof b.data !== "object") throw new Error("The backup has no data.");
  const counts: Record<string, number> = {};
  for (const [store, fields] of Object.entries(REQUIRED) as [StoreName, string[]][]) {
    const rows = b.data[store] ?? [];
    if (!Array.isArray(rows)) throw new Error(`Backup section “${store}” is damaged.`);
    rows.forEach((r, i) => {
      if (!r || typeof r !== "object" || fields.some((f) => !(f in (r as object)))) throw new Error(`Backup section “${store}”, record ${i + 1} is damaged.`);
    });
    counts[store] = rows.length;
  }
  return counts;
}

/** Replace everything on the device with the backup (all or nothing). */
export async function restoreBackup(raw: unknown): Promise<Record<string, number>> {
  const counts = checkBackup(raw);
  const b = raw as Backup;
  const stores = [...DATA_STORES, "kv"] as StoreName[];
  const lastBackup = await kvGet<string>("last_backup_at");
  await atomic(stores, (st) => {
    for (const s of stores) {
      st(s).clear();
      for (const r of (b.data[s] ?? []) as object[]) st(s).put(r);
    }
    // The restored file itself is a backup: keep the reminder quiet.
    st("kv").put({ key: "last_backup_at", value: lastBackup ?? b.exported_at });
  });
  return counts;
}

/** Ask the browser to keep this site's data even when the device is low on space. */
export async function requestPersistence(): Promise<boolean | null> {
  try {
    if (!navigator.storage?.persist) return null;
    if (await navigator.storage.persisted()) return true;
    return await navigator.storage.persist();
  } catch {
    return null;
  }
}
