# MCP + operator CLI — Second sweep

**Area:** `cursor-layla-mcp/server.py`, repo-root `layla.py`  
**Status:** Done  
**Template:** [MODULE_SWEEP_TEMPLATE.md](MODULE_SWEEP_TEMPLATE.md)

---

## 1. Scope and entry points

| Surface | Role |
|---------|------|
| **Cursor MCP** | `cursor-layla-mcp/server.py` — stdio MCP server; tools call local FastAPI |
| **CLI** | `layla.py` — httpx-based commands: `ask`, `wakeup`, `approve`, `pending`, `study`, `status`, etc. |

**Out of scope:** Remote-hosted Layla (see `docs/REMOTE_ARCHITECTURE.md`); MCP does not add new server-side routes.

---

## 2. Data flow

### MCP (`LAYLA_BASE_URL`)

- Default **`LAYLA_BASE`** = `os.environ.get("LAYLA_BASE_URL", "http://127.0.0.1:8000")` (trailing slash not required; paths append `/agent`, `/approve`, `/pending`, `/learn/`, etc.).
- **`chat_with_layla`:** POST JSON to `{LAYLA_BASE}/agent` — optional streaming via `_agent_stream_sync()` (SSE aggregation).
- **`get_pending_approvals`:** GET `{LAYLA_BASE}/pending`.
- **`approve_action`:** POST `{LAYLA_BASE}/approve` with `{"id": "<uuid>"}`.
- **`add_learning`**, **`start_study_session`**, **`analyze_repo_for_study`:** map to existing HTTP APIs on the same base.
- Workspace: `_normalize_workspace_root()` for context passed into payloads; infers git top-level when omitted.

### CLI (`layla.py`)

- Hardcoded **`BASE_URL = "http://localhost:8000"`** (same origin as default agent; change code or use MCP env if you bind elsewhere).
- Uses **httpx** for `/agent`, `/health`, `/approve`, `/learn/`, etc.

See [ARCHITECTURE.md](../ARCHITECTURE.md) request flow and **Operator surfaces** subsection below.

---

## 3. Safety and invariants

| Invariant | Notes |
|-----------|--------|
| No bypass of approval | MCP/CLI only forward requests; `allow_write` / `allow_run` and tool `approval_required` still enforced on the server |
| Local trust | Default URLs assume localhost; treat `LAYLA_BASE_URL` like a secret channel to your agent |
| No shell from MCP by default | Tool execution is server-side; MCP does not spawn user shells |

---

## 4. Failure modes and logging

| Failure | Behavior |
|---------|----------|
| Agent not running | `urllib` / httpx connection errors; `layla.py` exits with message to start uvicorn |
| SSE parse errors | `_agent_stream_sync` skips malformed lines; final text from `done` or joined tokens |
| Approve invalid id | Server response surfaced to Cursor |

---

## 5. Tests and verification

- **Manual / release:** [RELEASE_CHECKLIST.md](RELEASE_CHECKLIST.md) MCP smoke steps.
- **Server contract:** `agent/tests/` cover `/agent`, `/approve`; MCP is a thin HTTP client.

---

## 6. Open risks / follow-ups

- **URL drift:** CLI `localhost` vs MCP `127.0.0.1` — both resolve locally; document if binding to `0.0.0.0` only.
- **Timeouts:** MCP uses long timeouts for `/agent`; align with `max_runtime_seconds` in [PRODUCTION_CONTRACT.md](PRODUCTION_CONTRACT.md).
