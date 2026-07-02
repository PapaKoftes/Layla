/* Layla PWA — cache static UI; API calls stay network-first.
 *
 * Static UI uses stale-while-revalidate: the cached asset is served immediately
 * (fast + offline), while a fresh copy is fetched in the background and stored,
 * so the NEXT load picks up UI updates automatically — no manual cache-version
 * bump required for changes to reach existing installs. Bump CACHE only to force
 * an immediate purge. The activate handler deletes superseded caches.
 */
const CACHE = "layla-ui-v5";
const PRECACHE = [
  "/ui/",
  "/manifest.json",
  "/layla-ui/css/layla.css",
  "/layla-ui/css/layla-rebuild.css",
  "/layla-ui/main.js",
  "/layla-ui/core/bus.js",
  "/layla-ui/core/state.js",
  "/layla-ui/core/overlay.js",
  "/layla-ui/core/compat.js",
  "/layla-ui/services/api.js",
  "/layla-ui/services/health.js",
  "/layla-ui/services/utils.js",
  "/layla-ui/components/models.js",
];

self.addEventListener("install", (event) => {
  event.waitUntil(
    caches.open(CACHE).then((cache) => cache.addAll(PRECACHE).catch(() => undefined))
  );
  self.skipWaiting();
});

self.addEventListener("activate", (event) => {
  // Purge old cache versions so a stale bundle can never be served after an update.
  event.waitUntil(
    caches.keys()
      .then((keys) => Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k))))
      .then(() => self.clients.claim())
  );
});

self.addEventListener("fetch", (event) => {
  const req = event.request;
  if (req.method !== "GET") return;
  const url = new URL(req.url);
  if (url.pathname.startsWith("/ui") || url.pathname.startsWith("/layla-ui") || url.pathname === "/manifest.json") {
    event.respondWith(
      caches.open(CACHE).then((cache) =>
        cache.match(req).then((hit) => {
          // Background refresh: fetch fresh, update cache; fall back to cache on failure.
          const network = fetch(req).then((res) => {
            if (res && res.ok) cache.put(req, res.clone());
            return res;
          }).catch(() => hit);
          // Serve cache immediately if present (stale-while-revalidate); else wait for network.
          return hit || network;
        })
      )
    );
  }
});
