# Remote architecture (§16)

## Current: local-first execution

Layla runs **locally** on the user's machine:

- One FastAPI server (`agent/main.py`) bound to `localhost:8000` by default
- One SQLite database (`layla.db`) on disk
- LLM access via `agent/services/llm_gateway.py` (local Llama or optional `llama_server_url`)
- All tool execution (read_file, write_file, run_python, etc.) runs on the same machine
- No telemetry or cloud dependency for the core chat/agent loop

This is **local-first**: the product is designed so that data and execution stay on the user's side.

---

## §16 Remote: implemented (production-safe, minimal)

Remote access is **opt-in** and **does not introduce autonomy**. Same approval flow and tool gating as local. Writable paths are still constrained by the **sandbox** (see [OPERATOR_SANDBOX.md](OPERATOR_SANDBOX.md)) and [OPERATOR_APPROVALS.md](OPERATOR_APPROVALS.md) for the approval UI flow.

### Config (`runtime_config.json`)

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| `remote_enabled` | bool | false | When true, allow non-localhost requests (subject to auth and allowlist). |
| `remote_api_key` | str \| null | null | Required for non-localhost when `remote_enabled` is true. Sent as `Authorization: Bearer <key>`. |
| `remote_allow_endpoints` | list[str] | [] | If non-empty, exact list of path prefixes allowed for remote requests. If empty, derived from `remote_mode`. |
| `remote_mode` | "observe" \| "interactive" | "observe" | **observe**: allow only `/wakeup`, `/project_discovery`, `/health`. **interactive**: also allow `/agent`, `/v1/chat/completions`, `/learn/`. |

### Binding

- When `remote_enabled` is **false**, run the server bound to **127.0.0.1** (localhost only). External requests cannot reach it.
- When `remote_enabled` is **true**, run the server bound to **0.0.0.0** to accept external connections, e.g.:
  - `uvicorn main:app --host 0.0.0.0 --port 8000`

### Auth middleware (`main.py`)

- If `remote_enabled` is false → all requests pass through.
- If request client is **localhost** (127.0.0.1, localhost, ::1, testclient) → no auth required.
- If request is **non-localhost**:
  - If `remote_api_key` is not set or empty → **403** (remote_access_requires_api_key).
  - If `Authorization: Bearer <key>` is missing or wrong → **401** (unauthorized).
  - If path is not in the allowlist (derived from `remote_mode` or `remote_allow_endpoints`) → **403** (forbidden).

### No autonomy added

- No background loops, scheduling, or auto-execution for remote.
- All tool approvals work exactly as local; remote only exposes the same API over authenticated HTTP.
- **System is non-autonomous by design** (see IMPLEMENTATION_STATUS.md).

### Tests

- `agent/tests/test_remote.py`: remote disabled, localhost bypass, non-localhost 401/403, correct key allowed, `remote_mode` observe (blocks /agent) and interactive (allows /agent).

---

## Future extensions (not in scope)

- TLS / HTTPS termination
- Rate limiting per key
- Optional IP allowlist in addition to API key
