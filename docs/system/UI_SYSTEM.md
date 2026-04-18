# UI system (as implemented)

Sources: [`agent/main.py`](../../agent/main.py), [`agent/ui/index.html`](../../agent/ui/index.html), [`agent/ui/js/layla-app.js`](../../agent/ui/js/layla-app.js), [`agent/ui/js/layla-bootstrap.js`](../../agent/ui/js/layla-bootstrap.js).

## Serving

- **`GET /`**, **`GET /ui`**: HTML from **`agent/ui/index.html`** with **`Cache-Control: no-store`** ([`main.py`](../../agent/main.py)).
- **`/layla-ui`**: static mount of **`agent/ui`** directory.
- **`GET /manifest.json`**, **`GET /sw.js`**: PWA assets when present.

## Browser → API (representative)

From [`layla-app.js`](../../agent/ui/js/layla-app.js) / [`layla-bootstrap.js`](../../agent/ui/js/layla-bootstrap.js):

- **`POST /agent`** — primary chat/agent request.
- **`GET /session/stats`** — token/session stats display.
- **`POST /autonomous/run`** — Tier-0 investigation from UI when enabled.
- **`GET /agent/tasks`**, **`GET /agent/tasks/{id}`**, **`DELETE /agent/tasks/{id}`** — background task polling.

This document lists **what exists in source**; it does not prescribe UI behavior changes.
