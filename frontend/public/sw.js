/*
 * Investor Intelligence service worker (hand-written, no third-party deps).
 *
 * - App shell & static assets: cache-first (hashed /_next/static files are immutable).
 * - Page navigations: network-first, falling back to the cached page, then the cached home page.
 * - GET /api/*: network-first; on failure, serve the last saved response with an
 *   `x-ii-cached-at` header so the UI can say how old the data is.
 *   Never caches /api/auth/* mutations, exports or backups.
 * - Per-user API caches are deleted by the page on sign-in and sign-out.
 */
const VERSION = "v5";
const SHELL = `ii-shell-${VERSION}`;
const STATIC = `ii-static-${VERSION}`;
const API = `ii-api-${VERSION}`;
const PRECACHE = ["/", "/login", "/markets", "/watchlist", "/analyst", "/portfolio", "/notes", "/company", "/settings", "/sources", "/documents", "/screener", "/compare", "/valuation", "/news", "/alerts", "/manifest.webmanifest", "/icons/icon-192.png"];
const API_NO_CACHE = [/^\/api\/documents\/\d+\/file/, /^\/api\/ai\/status/, /^\/api\/me\/export/, /^\/api\/admin\/backups/, /^\/api\/auth\/sessions/, /^\/api\/system\/status/];

self.addEventListener("install", (event) => {
  event.waitUntil(
    caches.open(SHELL).then((c) => Promise.all(PRECACHE.map((u) => c.add(u).catch(() => undefined)))).then(() => self.skipWaiting()),
  );
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches
      .keys()
      .then((keys) => Promise.all(keys.filter((k) => !k.endsWith(VERSION)).map((k) => caches.delete(k))))
      .then(() => self.clients.claim()),
  );
});

async function withCachedHeader(response, savedAt) {
  const headers = new Headers(response.headers);
  headers.set("x-ii-cached-at", savedAt);
  return new Response(await response.blob(), { status: response.status, statusText: response.statusText, headers });
}

async function apiNetworkFirst(request) {
  const cache = await caches.open(API);
  try {
    const res = await fetch(request);
    if (res.ok) {
      const headers = new Headers(res.headers);
      headers.set("x-ii-saved-at", new Date().toISOString());
      const copy = new Response(await res.clone().blob(), { status: res.status, statusText: res.statusText, headers });
      cache.put(request, copy).catch(() => undefined);
    } else if (res.status === 401) {
      // Signed out: drop everything user-specific.
      caches.delete(API);
    }
    return res;
  } catch {
    const hit = await cache.match(request);
    if (hit) return withCachedHeader(hit, hit.headers.get("x-ii-saved-at") || "");
    return new Response(JSON.stringify({ detail: "Offline and no saved copy of this data is available." }), {
      status: 503,
      headers: { "Content-Type": "application/json" },
    });
  }
}

async function pageNetworkFirst(request) {
  const cache = await caches.open(SHELL);
  try {
    const res = await fetch(request);
    if (res.ok) cache.put(request, res.clone()).catch(() => undefined);
    return res;
  } catch {
    const url = new URL(request.url);
    return (
      (await cache.match(request, { ignoreSearch: true })) ||
      (await cache.match(url.pathname)) ||
      (await cache.match("/")) ||
      new Response("Offline", { status: 503, headers: { "Content-Type": "text/plain" } })
    );
  }
}

async function staticCacheFirst(request) {
  const cache = await caches.open(STATIC);
  const hit = await cache.match(request);
  if (hit) return hit;
  const res = await fetch(request);
  if (res.ok) cache.put(request, res.clone()).catch(() => undefined);
  return res;
}

self.addEventListener("fetch", (event) => {
  const { request } = event;
  if (request.method !== "GET") return;
  const url = new URL(request.url);
  if (url.origin !== self.location.origin) return;

  if (url.pathname.startsWith("/api/")) {
    if (url.pathname.startsWith("/api/auth/") && url.pathname !== "/api/auth/me") return;
    if (API_NO_CACHE.some((r) => r.test(url.pathname))) return;
    event.respondWith(apiNetworkFirst(request));
    return;
  }
  if (request.mode === "navigate") {
    event.respondWith(pageNetworkFirst(request));
    return;
  }
  if (url.pathname.startsWith("/_next/static/") || url.pathname.startsWith("/icons/") || url.pathname.startsWith("/splash/")) {
    event.respondWith(staticCacheFirst(request));
  }
});

// Web Push (optional): show the notification and open the linked page on tap.
self.addEventListener("push", (event) => {
  let data = { title: "Investor Intelligence", body: "", url: "/" };
  try {
    data = { ...data, ...event.data.json() };
  } catch {}
  event.waitUntil(
    self.registration.showNotification(data.title, {
      body: data.body,
      icon: "/icons/icon-192.png",
      badge: "/icons/icon-192.png",
      data: { url: typeof data.url === "string" && data.url.startsWith("/") ? data.url : "/" },
    }),
  );
});

self.addEventListener("notificationclick", (event) => {
  event.notification.close();
  const url = event.notification.data?.url || "/";
  event.waitUntil(
    self.clients.matchAll({ type: "window", includeUncontrolled: true }).then((wins) => {
      for (const w of wins) {
        if ("focus" in w) {
          w.navigate(url);
          return w.focus();
        }
      }
      return self.clients.openWindow(url);
    }),
  );
});

self.addEventListener("message", (event) => {
  if (event.data === "clear-user-cache") event.waitUntil(caches.delete(API));
});
