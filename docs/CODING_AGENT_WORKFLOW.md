# Coding agent workflow (Claude Code–style patterns, local)

This document maps **how to work like a hosted coding agent** using Layla: **Web UI**, **POST /agent**, **MCP** (Cursor), and **background** jobs.

## When to use what

| Mode | Route / entry | Use when |
|------|----------------|----------|
| Interactive turn | `POST /agent` | Default chat + tool loop from Web UI or CLI |
| Background / long run | `POST /agent/background` via [`agent/routers/agent_tasks.py`](../agent/routers/agent_tasks.py) | Long tasks; poll `GET /agent/tasks/{id}` for `progress_tail` |
| Tiny sub-agent | `POST /agents/spawn` | Isolated goal; same task store as background; see tests in `test_agents_spawn.py` |
| IDE | [`cursor-layla-mcp/server.py`](../cursor-layla-mcp/server.py) | Editor-integrated chat; same HTTP API |
| Optional pool (future) | MCP stdio client in [`agent/services/mcp_client.py`](../agent/services/mcp_client.py) | High-frequency `mcp_tools_call` may warrant a **session pool**; not required for correctness today |

## Approvals and diffs

Mutating tools hit **governance** and `GET /pending` with **diff preview** when the loop attaches it. Approve with `POST /approve` (optionally `grant_pattern` / session grant from the Web UI). This matches the “preview then apply” habit from IDE agents.

## Abort semantics

- **Streaming** `/agent`: disconnect can inject a synthetic user message (`client_abort_event` path in `agent_loop`).
- **Non-streaming** `/agent`: no open stream; cancellation is **best-effort** at loop boundaries.
- **Subprocess workers**: hard cancel via process terminate/kill when `background_use_subprocess_workers` is enabled.

## Model routing (quality)

Poor results on large refactors usually mean **wrong model tier** or **truncated context**, not a missing flag.

- Prefer **`coding_model`** / **`reasoning_model`** overrides in `runtime_config.json` when available (see [`services/model_router.py`](../agent/services/model_router.py) and [MODELS.md](../MODELS.md)).
- Use the Web UI header **model override** (remote / multi-backend setups) for one-off routing.
- Keep **`n_ctx`** aligned with your GPU RAM; undersized windows cause incoherent multi-file edits.

## Related

- [PARITY_AUDIT.md](PARITY_AUDIT.md) — status table vs reference patterns  
- [PARITY_BACKLOG.md](PARITY_BACKLOG.md) — MCP depth and sub-agent gaps  
