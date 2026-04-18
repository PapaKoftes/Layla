# Parity audit — Layla vs Claude Code / OpenClaude / Claw (reference patterns)

Reference zips are **design-only**; this repo implements features natively in Python/HTML. Status: **IMPLEMENTED** (in tree), **IN-PLAN** (this document / backlog), **FUTURE** (not scheduled).

| Area | Item | Status |
|------|------|--------|
| Tool safety | Shell network denylist + safe-regex auto-approval | IMPLEMENTED (`registry` / system shell path) |
| Tool safety | Command injection warning / risk | IMPLEMENTED |
| Tool safety | Prefix permission grants (`tool_permission_grants`, approve + `grant_pattern`) | IMPLEMENTED |
| Tool safety | Per-session allowlist (`save_for_session` on approve) | IMPLEMENTED (`routers/approvals.py` + `services/session_grants.py`; Web UI checkbox `sg-*` in `ui/js/layla-app.js` → `approveId(..., checked)`) |
| File tools | Read-before-write mtime guard | IMPLEMENTED |
| File tools | Unified diff / patch preview on approval | IMPLEMENTED (`agent_loop._approval_preview_diff`) |
| Context | HyDE in hybrid memory search (`hyde_enabled`) | IMPLEMENTED |
| Context | Auto-compact at high fill (`maybe_auto_compact` on assistant append) | IMPLEMENTED (`shared_state.append_conv_history`) |
| Context | SSE `approaching_context_limit` / `context_critical` | IMPLEMENTED (`_emit_context_window_ux` + router) |
| Context | `POST /compact`, `GET /ctx_viz` | IMPLEMENTED |
| Context | Token bar + session stats in UI | IMPLEMENTED (`index.html`, `/session/stats`) |
| Agent loop | `think` action + SSE | IMPLEMENTED |
| Agent loop | Concurrent read-only tool batches | IMPLEMENTED (`decision["batch_tools"]` + `ThreadPoolExecutor` when primary tool is `concurrency_safe`; see `agent_loop` D1 block; tests: `test_agent_loop_batch_tools.py`) |
| Agent loop | Synthetic message on client abort / disconnect (streaming) | IMPLEMENTED (`client_abort_event` + `_inject_cancel_message`; `POST /agent` stream watches `Request.is_disconnected`) |
| Project | Git + instruction file injection in system head | IMPLEMENTED (`agent_loop` / orchestrator) |
| Project | Session prompt history `GET /history` + UI ↑ | IMPLEMENTED |
| Skills | Loader + `GET /skills` + system head injection | IMPLEMENTED (`services/skills.py`) |
| Skills | Workspace UI tab | IMPLEMENTED |
| Inference | Ollama via `ollama_base_url` + `inference_backend` | IMPLEMENTED (`inference_router.ollama_http_base`, `/health.backends`) |
| MCP | Cursor MCP server | IMPLEMENTED (`cursor-layla-mcp/`) |
| MCP | Full MCP *client* in agent | IMPLEMENTED (`mcp_session_call_tool`, `mcp_session_list_tools`, `mcp_session_list_resources`, `mcp_session_read_resource`; registry `mcp_tools_call`, `mcp_list_mcp_tools`, `mcp_list_mcp_resources`, `mcp_read_mcp_resource`, `mcp_operator_auth_hint`; optional `mcp_inject_tool_summary_in_decisions` TTL block in `_llm_decision`; opt-in via `mcp_client_enabled` / `mcp_stdio_servers`). **Latency:** each stdio MCP invocation uses a short subprocess session by design; optional **session pool** for hot loops remains **FUTURE** — see [`PARITY_BACKLOG.md`](PARITY_BACKLOG.md). |
| Notebooks | Jupyter cell read/edit | IMPLEMENTED (`notebook_read_cells`, `notebook_edit_cell`; requires `nbformat` in env) |
| Background tasks | Cancel (cooperative + hard) | IMPLEMENTED (`POST /agent/tasks/{id}/cancel`, `DELETE /agent/tasks/{id}`): **default thread** path sets `client_abort_event` on in-process `autonomous_run`; **`background_use_subprocess_workers`** → `services/background_subprocess.py` spawns `background_job_worker.py`, stores `worker_proc` / `worker_pid`, cancel → `terminate`/`kill` (+ optional psutil process tree). |
| Sub-agents | `dispatch_agent` style workers | PARTIAL (`POST /agents/spawn` → same queue as `/agent/background`; shares cancel + `worker_mode` semantics above; tests: `test_agents_spawn.py`, `test_background_task_cancel.py`, `test_background_subprocess.py`) |
| Agent memory | Durable per-workspace JSON map + multi-iteration background | IMPLEMENTED (`services/project_memory.py`, `.layla/project_memory.json`, tools `scan_repo` / `update_project_memory`, prompt injection in `agent_loop._build_system_head`, `understand_mode` on `POST /agent`, `plan_mode` optional persist to memory, `continuous` + `max_iterations` + `iteration_delay_seconds` on background enqueue + `background_job_worker.py`) |
| Shell | Persistent shell sessions | IMPLEMENTED (`shell_sessions.py`; caps/TTL per plan) |

Update this table when behavior changes. Path/symbol anchors for automated checks live in [`parity_manifest.yaml`](parity_manifest.yaml) (see `agent/tests/test_parity_manifest.py`).

**Gap checklist (files, tests, next steps):** [`PARITY_BACKLOG.md`](PARITY_BACKLOG.md).

**Claude Code Unpacked** (unofficial loop/tool map): [`CCUNPACKED_ALIGNMENT.md`](CCUNPACKED_ALIGNMENT.md) — how Layla lines up and what to build next.
