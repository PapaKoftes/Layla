/* Layla PWA — cache static UI; API calls stay network-first. */
const CACHE = "layla-ui-v1";
const PRECACHE = [
  "/ui/",
  "/manifest.json",
  "/layla-ui/css/layla.css",
  "/layla-ui/js/layla-bootstrap.js",
  "/layla-ui/js/layla-app.js",
  "/layla-ui/js/state.js",
  "/layla-ui/js/api.js",
  "/layla-ui/js/chat.js",
  "/layla-ui/js/sidebar.js",
  "/layla-ui/js/panels.js",
  "/layla-ui/js/layla-wizard.js",
  "/layla-ui/js/layla-conversations.js",
  "/layla-ui/js/layla-ui-phases.js",
  "/layla-ui/js/layla-sprites.js",
];

self.addEventListener("install", (event) => {
  event.waitUntil(
    caches.open(CACHE).then((cache) => cache.addAll(PRECACHE).catch(() => undefined))
  );
  self.skipWaiting();
});

self.addEventListener("activate", (event) => {
  event.waitUntil(self.clients.claim());
});

self.addEventListener("fetch", (event) => {
  const req = event.request;
  if (req.method !== "GET") return;
  const url = new URL(req.url);
  if (url.pathname.startsWith("/ui") || url.pathname.startsWith("/layla-ui") || url.pathname === "/manifest.json") {
    event.respondWith(
      caches.match(req).then((hit) => hit || fetch(req).then((res) => {
        const copy = res.clone();
        caches.open(CACHE).then((c) => c.put(req, copy)).catch(() => undefined);
        return res;
      }))
    );
  }
});
