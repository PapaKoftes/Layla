# POST `/agent` JSON response contract

Clients (Web UI, MCP, CLI, tests) should not assume a single flat shape: the router returns different **`state`** layouts depending on early exits vs the full `autonomous_run` path. This document lists the variants and stable fields.

**Implementation:** [`agent/routers/agent.py`](../agent/routers/agent.py).

---

## Common top-level keys (typical chat success)

- `response` — assistant text (or error/setup message).
- `state` — object; always includes **`steps`** as an array (possibly empty) after normalization (see below).
- `aspect`, `aspect_name`, `refused`, `refusal_reason`, `ux_states`, `memory_influenced`, `cited_sources`.
- Full loop responses also include `reasoning_mode`, `conversation_id`, `load`, `reasoning_tree_summary`.

`reasoning_tree_summary` may appear both at the top level and nested under `state.reasoning_tree_summary` (fast path and full loop).

---

## `state.status` discriminant

| `state.status` | When |
|----------------|------|
| `empty_message` | No `message` text; short-circuit before model. |
| `fast_path` | Trivial greeting/ack from `_quick_reply_for_trivial_turn` (no full loop). |
| `no_model` | Model not ready (`_no_model_response`). |
| `error` | Exception during `autonomous_run` in the router (rare). |
| `cache_hit` | Served from response cache (`state` merged from cached payload). |
| *(from loop)* `finished`, `timeout`, `system_busy`, `tool_limit`, `parse_failed`, `client_abort`, etc. | Returned inside `state` from `autonomous_run`. |

Plan mode (`plan_mode: true`) returns a **different top-level shape** (`status: plan_ready`, `plan`, `goal`, …) without the usual full-loop `state` object — see router. It also persists a draft in SQLite and returns **`plan_id`** (UUID string) plus **`plan_steps`** (normalized step list). Clients should prefer **`plan_id`** for **`POST /plans/{id}/approve`** and follow-up **`POST /agent`** requests with **`plan_id`** when **`planning_strict_mode`** is enabled.

**Understand mode** (`understand_mode: true`, requires `workspace_root` inside sandbox): deterministic scan + cognition sync — **no full LLM loop**. Top-level keys include `status` / `state.status` **`understand_done`**, `scan_repo` (tool-shaped result dict from `scan_workspace_into_memory`), `sync_repo_cognition` (same shape as the cognition sync tool). Optional `understand_index_semantic: true` enables semantic indexing during sync.

---

## `state.steps`

- **Full loop:** one entry per tool / think / reason step (see `agent_loop`); may be large.
- **Fast path / empty / no_model / error:** `steps` is **`[]`** (normalized so clients can always use `Array.isArray(state.steps)`).

---

## User-facing strings for limited runs

When `state.status` is set and the last step does not yield assistant text, the router fills `response` with fixed copy, including:

- `timeout` — request took too long.
- `system_busy` — CPU/RAM load gate.
- `tool_limit` — hit `max_tool_calls`.
- `parse_failed` — could not understand the request.

Tests: [`agent/tests/test_runtime_validation_plan.py`](../agent/tests/test_runtime_validation_plan.py).

---

## Live and subprocess evidence

- **Live multi-tool proof** (optional): `pytest -m slow agent/tests/test_runtime_validation_plan.py::test_live_post_agent_multi_tool_when_model_ready` — skips when no model; strict assertion requires ≥2 tool steps. Set `LAYLA_TRACE_CAPTURE=/path/to.json` to write the full response.
- **Subprocess worker + cancel:** same file, `test_subprocess_background_cancel_hard_kill` (uses a fake long-running child process; no GGUF in worker).

---

## Related

- [GOLDEN_FLOW.md](GOLDEN_FLOW.md) — lifecycle and approvals.
- [ARCHITECTURE.md](../ARCHITECTURE.md) — router entrypoints.
