/* Layla PWA — cache static UI; API calls stay network-first.
 *
 * Static UI uses stale-while-revalidate: the cached asset is served immediately
 * (fast + offline), while a fresh copy is fetched in the background and stored,
 * so the NEXT load picks up UI updates automatically — no manual cache-version
 * bump required for changes to reach existing installs. Bump CACHE only to force
 * an immediate purge. The activate handler deletes superseded caches.
 */
// v15 (BL-243/244): stale-while-revalidate would serve the OLD conversations.js/app.js/layla.css on
// the first load after this update, so the rail fix would look broken until a second reload — on a
// bug the operator has already been told was fixed three times. Bumping forces the activate handler
// to purge v14 immediately, so the fix is live on the first load.
//
// v16 (BL-270/271/272, BL-335): voice.js, obsidian.js, main.js, settings-full.js, chat-render.js,
// index.html and layla-rebuild.css all changed. Without a bump, the first load after this update serves
// the OLD modules from v15: the TTS toggle would still no-op, "Save appearance" would still lie, and the
// new appearance controls would render against JS that has never heard of them — i.e. every fix would
// look broken for reasons unrelated to the fix. A stale SW already produced two false results here.
//
// v17 (BL-250/BL-249/BL-374): wizard.js, setup.js, onboarding.js, chat-render.js, app.js, main.js,
// core/compat.js, index.html and layla.css all changed together — the wizard-gate fix, the first-run tour,
// and the honesty-copy fixes. compat.js now imports dismissOnboarding from onboarding.js and dismissTour
// from setup.js; a stale v16 setup.js exports neither, so serving the old graph against the new imports
// would fail to LINK and boot to a dead page. That was the previous attempt's exact failure — bump so the
// whole graph updates atomically on first load.
// v29 (BL-390): index.html, main.js, layla-rebuild.css and a NEW module (components/nav-groups.js)
// change together — the grouped feature navigation. main.js now imports nav-groups.js; a stale v28
// main.js does not, so the sidebar groups would render with no gate copy at all and the two gated
// entries would look available. Stale-while-revalidate would serve exactly that on the first load.
// v30 (BL-390 gate-truth fix): index.html, layla-rebuild.css, main.js and components/nav-groups.js
// change together — the gated nav entries are re-tagged against the flags their panels actually
// read (Deliberate is now UNGATED; Sync gates on syncthing_api_key, not remote), and the sidebar
// layout is fixed so all four group headings fit at 1366x768. A stale v29 index.html would keep asking /setup/gate-status about
// `multi_agent` and `remote` — the server still answers both, so the operator would go on being told
// a working panel is locked, and told to rotate a tunnel token that does not enable sync. A wrong
// answer that renders perfectly is exactly what stale-while-revalidate would serve here.
const CACHE = "layla-ui-v31";
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
          // cache:"reload" BYPASSES the browser HTTP cache so revalidation always hits the
          // network — otherwise a heuristically-cached CSS/JS makes stale-while-revalidate
          // serve stale forever (the SW re-caches the HTTP-cached stale copy). This is what
          // guarantees a UI update actually reaches the user on the next load.
          const network = fetch(new Request(req.url, { cache: "reload" })).then((res) => {
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
