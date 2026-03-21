# Web UI module — Second sweep

**Area:** `agent/ui/` (primary: `index.html`)  
**Status:** Done  
**Template:** [MODULE_SWEEP_TEMPLATE.md](MODULE_SWEEP_TEMPLATE.md)

---

## 1. Scope and entry points

| Kind | Location |
|------|----------|
| Static UI | [`agent/ui/index.html`](../agent/ui/index.html) — single-page app: chat, aspect selector / lock, sidebar panels, streaming to `POST /agent`, platform fetches |
| Delivery | [`agent/main.py`](../agent/main.py) — `GET /ui`, `GET /` (same HTML as `/ui`), optional `GET /manifest.json` from `agent/ui/manifest.json` or inline default |
| PWA asset | `agent/ui/manifest.json` (optional on disk) |

**Public HTTP:** `GET /ui`, `GET /` return `HTMLResponse` with **`Cache-Control: no-store`** (`_UI_NO_CACHE`). If `index.html` is missing or unreadable, server logs a warning and serves embedded **`_INLINE_UI`** fallback (minimal shell—not the full product UI).

**Out of scope:** TUI (`agent/tui.py`), MCP, and CLI surfaces (see [MCP_MODULE_SECOND_SWEEP.md](MCP_MODULE_SECOND_SWEEP.md)). Remote auth semantics follow server config (same as any browser client to FastAPI).

---

## 2. Data flow

1. Browser loads `/ui` or `/` → FastAPI reads resolved `AGENT_DIR / ui / index.html` and returns UTF-8 HTML.
2. Client JS calls same-origin APIs: `POST /agent` (JSON or SSE streaming), `GET /platform/models`, `/platform/knowledge`, `/platform/plugins`, `/platform/projects`, `/wakeup`, `/study_plans`, `/pending`, `/approve`, etc.
3. Panel ↔ API mapping is summarized in [`ARCHITECTURE.md`](../ARCHITECTURE.md) (Platform UI components table).

**Config:** The UI does not read `runtime_config.json` directly; behavior follows whatever the server exposes on endpoints and stream payloads.

---

## 3. Safety and invariants

| Invariant | Notes |
|-----------|--------|
| Path safety | Only `AGENT_DIR/ui/index.html` is read for the rich UI; no user-controlled path |
| Secrets | No API keys in static HTML; tokens use normal HTTP/session patterns the UI implements |
| Approval flow | Write/run still enforced server-side; UI displays approval UX when API returns `approval_required` |

**Silent failure to avoid:** Serving `_INLINE_UI` when the real file exists but read fails—operators should watch logs (`ui file read failed`).

---

## 4. Failure modes and logging

| Failure | Behavior |
|---------|----------|
| Missing or unreadable `index.html` | `logger.warning`; `_INLINE_UI` served; **tests expect full file** for repair markers |
| Manifest missing/invalid | Default JSON manifest returned from route handler |
| Platform API errors | Client-side handling; server returns HTTP status per router |

---

## 5. Tests and verification

| File | Covers |
|------|--------|
| [`agent/tests/test_platform_ui.py`](../agent/tests/test_platform_ui.py) | `GET /platform/models`, `/platform/plugins`, `/platform/knowledge`, `/platform/projects`; `GET /ui` 200 and LAYLA branding; **chat repair**: `#msg-input`, `#send-btn`, `triggerSend`, `bindChatInputNow`, keydown + `activeElement`, `finally` block; **Cache-Control** `no-store`; on-disk `index.html` markers (`test_ui_chat_repair_in_file`) |

Run:

```bash
cd agent && pytest tests/test_platform_ui.py -q
```

---

## 6. Open risks / follow-ups

- **`_INLINE_UI`** in `main.py` can drift from `agent/ui/index.html` if someone edits only one; routes are intended to prefer the file; root and `/ui` stay aligned by sharing the same handler logic.
- Large `index.html` is hard to review in one pass; prefer small targeted edits and rely on `test_platform_ui` for regression-sensitive chat input behavior.

---

**After publishing:** Tracked in [`MODULE_SWEEP_STATUS.md`](MODULE_SWEEP_STATUS.md); see [`CHANGELOG.md`](../CHANGELOG.md) for user-visible doc notes.
