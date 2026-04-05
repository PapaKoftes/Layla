# Golden flow — canonical request lifecycle

Single reference for how a normal chat turn moves through Layla, where tools and approvals hook in, and how memory is written. Use this to avoid drift between Web UI, CLI, MCP, and TUI (all call the same HTTP API unless noted).

**Related:** [ARCHITECTURE.md](../ARCHITECTURE.md) (full flow), [PRODUCTION_CONTRACT.md](PRODUCTION_CONTRACT.md) (guarantees), [AGENTS.md](../AGENTS.md) (file map).

---

## 1. Chat turn: `POST /agent`

1. **Router** ([`agent/routers/agent.py`](../agent/routers/agent.py)): reads `message`, `workspace_root`, `allow_write`, `allow_run`, `aspect_id`, `conversation_id`, optional stream/image flags. Fast paths: empty message, trivial greeting (no full loop), optional response cache.
2. **Core** ([`agent/agent_loop.py`](../agent/agent_loop.py) `autonomous_run`): loads config via `runtime_safety.load_config()`, classifies reasoning depth, selects aspect, may run planner / cognitive workspace, then enters the **decision loop** (`max_tool_calls`, `max_runtime_seconds` from effective config).
3. **Decision** (`_llm_decision` + `decision_schema`): JSON `action` is `tool`, `reason`, or `none`. Tools are validated (policy, args, loop detection) before execution.
4. **Response**: Router builds JSON with `response`, `state` (steps, status), `reasoning_mode`, `conversation_id`, etc. On success it appends to session history and calls `create_conversation` / `append_conversation_message` in SQLite when possible. **Fast path, empty message, and no-model branches use different `state.status` values but still expose `state.steps` (often empty); see [POST_AGENT_RESPONSE_CONTRACT.md](POST_AGENT_RESPONSE_CONTRACT.md).**

**There is no automatic second hop** after a tool returns `approval_required` inside the same HTTP request: the run finishes with that step in `state.steps`. The client must call `POST /approve` and usually send a **follow-up** `POST /agent` if the user wants another model turn.

---

## 2. Tool gating and `approval_required`

- **Mutating tools** (`write_file`, `apply_patch`, `shell`, `run_python`, `git_commit`, etc.) check `allow_write` / `allow_run` and `runtime_safety.require_approval(...)`.
- When approval is required, the loop calls `_write_pending(tool, args)` → entries in [`agent/.governance/pending.json`](../agent/.governance/) (via [`agent/main.py`](../agent/main.py) `shared_state` readers).
- Tool result shape includes `reason: approval_required`, `approval_id`, and a short message.

---

## 3. `POST /approve` and `GET /pending`

- [`agent/routers/approvals.py`](../agent/routers/approvals.py): loads pending list, finds `id`, marks approved, runs **`TOOLS[tool].fn(**args)`** synchronously, writes result back, appends audit line.
- **Resume is not wired into `autonomous_run`**: approving executes the tool only; it does not re-enter the agent loop. The Web UI and other clients refresh pending and continue the conversation with a new user message if needed.

---

## 4. Memory writes

- **Conversation rows**: after each successful `/agent` reply, router persists user/assistant lines when DB helpers succeed.
- **Learnings / vectors**: `POST /learn/` → `db.add_learning` + vector store; distillation may run after outcomes (`layla/memory/distill.py`) when enabled.
- **Semantic recall** on a turn uses Chroma + fallbacks; failures are logged; see PRODUCTION_CONTRACT.

---

## 5. MCP, CLI, TUI

- **MCP** ([`cursor-layla-mcp/server.py`](../cursor-layla-mcp/server.py)): HTTP to the same `LAYLA_BASE_URL` endpoints (`/agent`, `/approve`, `/pending`, `/learn/`, etc.).
- **CLI** (`layla.py`): same HTTP surface.
- **TUI**: same API; behavior should match the golden flow above.

---

## 6. Observability (operator snapshot)

- **`GET /health`**: `active_model`, `effective_config` (sanitized + `effective_caps`), `features_enabled`, `dependencies` (optional import / Chroma vector probe with `?deep=true`). See [PRODUCTION_CONTRACT.md](PRODUCTION_CONTRACT.md).
- **`GET /health/deps`**: minimal `{ dependencies: { ... } }` with optional `?deep=true`.

---

## 7. Fabrication assist

[`fabrication_assist/`](../fabrication_assist/) is an **adapter and scaffolding layer** (schemas, session, subprocess runner). It is **not** part of the core `/agent` loop above unless explicitly integrated by a tool or separate service. It does not replace Layla’s kernel, geometry engine, or deterministic manufacturing pipeline by itself.

---

## 8. Future: event-driven UI

Today the Web UI uses **polling** (`/health` on an interval) for global status. **SSE/WebSocket** push for pending approvals and health is a possible phase-2 improvement; contracts above remain the source of truth.

---

## 9. Regression test

HTTP golden path (mocked LLM decision + completion only): [`agent/tests/test_golden_flow_http.py`](../agent/tests/test_golden_flow_http.py) — `POST /agent` → `write_file` + `approval_required` → `POST /approve` → follow-up `POST /agent`.
