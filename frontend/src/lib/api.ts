/**
 * Data access for the pages. There is no server: requests are answered on the device
 * from IndexedDB (see lib/local/api.ts). The `/api/...` paths are kept as stable keys
 * for SWR caching and to keep the pages simple.
 */
import { ApiError } from "./errors";

export { ApiError };

export async function api<T = unknown>(path: string, init: { method?: string; json?: unknown } = {}): Promise<T> {
  const method = (init.method ?? "GET").toUpperCase();
  const { handle } = await import("./local/api");
  try {
    // Plain JSON copy: callers get the same shapes a REST API would return, never live objects.
    const result = await handle(method, path, init.json);
    return (result === undefined ? undefined : JSON.parse(JSON.stringify(result))) as T;
  } catch (e) {
    if (e instanceof ApiError) throw e;
    throw new ApiError(500, e instanceof Error ? e.message : "Unexpected error while reading on-device data");
  }
}

export const fetcher = <T,>(path: string) => api<T>(path);
