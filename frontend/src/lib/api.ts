/**
 * Same-origin API client for the FastAPI backend.
 * Mutations send a custom header that the backend requires (CSRF defence).
 */

export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

type CacheListener = (cachedAt: string | null) => void;
const listeners = new Set<CacheListener>();
let lastCachedAt: string | null = null;

/** Notified when a response came from the offline cache (service worker). */
export function onCacheStatus(fn: CacheListener) {
  listeners.add(fn);
  fn(lastCachedAt);
  return () => listeners.delete(fn);
}

function setCacheStatus(v: string | null) {
  if (v === lastCachedAt) return;
  lastCachedAt = v;
  listeners.forEach((l) => l(v));
}

function errorMessage(body: unknown, fallback: string): string {
  if (body && typeof body === "object" && "detail" in body) {
    const d = (body as { detail: unknown }).detail;
    if (typeof d === "string") return d;
    if (Array.isArray(d) && d.length) {
      return d
        .map((e) => {
          const msg = String(e?.msg ?? "Invalid value").replace(/^Value error, /, "");
          const field = Array.isArray(e?.loc) ? e.loc[e.loc.length - 1] : "";
          return field && field !== "body" ? `${String(field).replace(/_/g, " ")}: ${msg}` : msg;
        })
        .join(" · ");
    }
  }
  return fallback;
}

export async function api<T = unknown>(path: string, init: RequestInit & { json?: unknown } = {}): Promise<T> {
  const { json, headers, ...rest } = init;
  const method = (rest.method ?? "GET").toUpperCase();
  const h = new Headers(headers);
  if (method !== "GET") h.set("X-Requested-With", "InvestorIntelligence");
  if (json !== undefined) h.set("Content-Type", "application/json");
  let res: Response;
  try {
    res = await fetch(path, {
      ...rest,
      method,
      headers: h,
      body: json !== undefined ? JSON.stringify(json) : rest.body,
      credentials: "same-origin",
    });
  } catch {
    throw new ApiError(0, "You appear to be offline. The server could not be reached.");
  }
  if (method === "GET") setCacheStatus(res.headers.get("x-ii-cached-at"));
  if (res.status === 204) return undefined as T;
  const body = await res.json().catch(() => null);
  if (!res.ok) {
    const fallback = res.status === 503 ? "Offline and no saved copy of this data is available." : `Request failed (${res.status})`;
    throw new ApiError(res.status, errorMessage(body, fallback));
  }
  return body as T;
}

export const fetcher = <T,>(path: string) => api<T>(path);

/** Remove any per-user data cached for offline use (call on sign-in/out). */
export async function clearOfflineCache() {
  if (typeof caches === "undefined") return;
  const keys = await caches.keys();
  await Promise.all(keys.filter((k) => k.startsWith("ii-api")).map((k) => caches.delete(k)));
}
