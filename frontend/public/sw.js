/*
 * Investor Intelligence service worker (hand-written, no dependencies).
 *
 * The app has no server: your data lives in IndexedDB on the device. This worker only
 * keeps the app's own files available offline.
 * - Pages: network-first (so updates arrive when online), cached copy when offline.
 * - Static files (hashed /_next/static, icons): cache-first.
 * Works under a sub-path (e.g. GitHub Pages "/<repository>/"): paths are relative to the scope.
 */
const VERSION = "v7";
const SHELL = `ii-shell-${VERSION}`;
const STATIC = `ii-static-${VERSION}`;
const BASE = new URL(self.registration.scope).pathname; // ends with "/"
const PAGES = ["", "watchlist/", "portfolio/", "notes/", "prices/", "settings/"];
const PRECACHE = [...PAGES, "manifest.webmanifest", "icons/icon-192.png"].map((p) => BASE + p);

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

async function pageNetworkFirst(request) {
  const cache = await caches.open(SHELL);
  try {
    const res = await fetch(request);
    if (res.ok) cache.put(request, res.clone()).catch(() => undefined);
    return res;
  } catch {
    const url = new URL(request.url);
    const path = url.pathname.endsWith("/") ? url.pathname : `${url.pathname}/`;
    return (
      (await cache.match(request, { ignoreSearch: true })) ||
      (await cache.match(path)) ||
      (await cache.match(BASE)) ||
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
  if (url.origin !== self.location.origin || !url.pathname.startsWith(BASE)) return;
  if (request.mode === "navigate") {
    event.respondWith(pageNetworkFirst(request));
    return;
  }
  const rel = url.pathname.slice(BASE.length);
  if (rel.startsWith("_next/static/") || rel.startsWith("icons/") || rel.startsWith("splash/")) {
    event.respondWith(staticCacheFirst(request));
  }
});
