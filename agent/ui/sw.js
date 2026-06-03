/* Layla PWA service worker.
 *
 * Strategy: NETWORK-FIRST for UI assets so code/style updates land immediately;
 * the cache is only a fallback for offline use. (The previous cache-first
 * strategy served stale JS/CSS forever because the cache name never changed.)
 * Bump CACHE whenever the offline shell needs to be invalidated.
 */
const CACHE = "layla-ui-v2";

// Minimal offline shell. Everything else is cached opportunistically on fetch,
// so this list does not need to enumerate every module.
const PRECACHE = [
  "/ui/",
  "/manifest.json",
];

self.addEventListener("install", (event) => {
  event.waitUntil(
    caches.open(CACHE).then((cache) => cache.addAll(PRECACHE).catch(() => undefined))
  );
  self.skipWaiting();
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches.keys()
      .then((keys) => Promise.all(
        keys.filter((k) => k !== CACHE).map((k) => caches.delete(k))
      ))
      .then(() => self.clients.claim())
  );
});

self.addEventListener("fetch", (event) => {
  const req = event.request;
  if (req.method !== "GET") return;
  const url = new URL(req.url);
  const isUiAsset =
    url.pathname.startsWith("/ui") ||
    url.pathname.startsWith("/layla-ui") ||
    url.pathname === "/manifest.json";
  if (!isUiAsset) return; // API and everything else: let the network handle it.

  // Network-first: try the network, fall back to cache only when offline.
  event.respondWith(
    fetch(req)
      .then((res) => {
        const copy = res.clone();
        caches.open(CACHE).then((c) => c.put(req, copy)).catch(() => undefined);
        return res;
      })
      .catch(() => caches.match(req))
  );
});
