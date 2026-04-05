# Parity backlog — gaps vs Claude-style reference patterns

Companion to [`PARITY_AUDIT.md`](PARITY_AUDIT.md). Each row here is **not fully done** or is **intentionally different** from the reference trees under `integrations/` and optional root-level clones.

**How to use:** pick a row → implement in `agent/` → add tests → update [`PARITY_AUDIT.md`](PARITY_AUDIT.md) and (if needed) [`parity_manifest.yaml`](parity_manifest.yaml).

---

## 1. IN-PROGRESS

### MCP client — deeper parity (optional)

| | |
|---|---|
| **Parity row** | MCP — Full MCP *client* in agent (beyond minimal slice) |
| **Done today (minimal slice)** | [`mcp_session_call_tool`](../agent/services/mcp_client.py) + [`mcp_session_list_tools`](../agent/services/mcp_client.py) (`tools/list`); registry [`mcp_tools_call`](../agent/layla/tools/registry.py) + [`mcp_list_mcp_tools`](../agent/layla/tools/registry.py); `mcp_tools_call` gated like `shell` in [`agent_loop`](../agent/agent_loop.py); [`test_mcp_client_stdio.py`](../agent/tests/test_mcp_client_stdio.py). See [`CCUNPACKED_ALIGNMENT.md`](CCUNPACKED_ALIGNMENT.md). |
| **Still missing vs “full” MCP** | MCP tools not merged into the LLM’s native tool/schema list (by design: TTL summary + `mcp_tools_call`); no long-lived stdio session across turns (each call is a short subprocess session). |
| **Done / discoverability** | `resources/list` + `resources/read` registry tools; `mcp_operator_auth_hint` for OAuth posture; see [`CCUNPACKED_ALIGNMENT.md`](CCUNPACKED_ALIGNMENT.md). |
| **Suggested next** | Optional `mcp_agent_bridge`: session pool if latency matters; optional official Python MCP SDK as extra. |

---

## 2. PARTIAL (by design or scope)

### Sub-agents / worker dispatch

| | |
|---|---|
| **Parity row** | Sub-agents — `dispatch_agent` style workers |
| **Done today** | [`agent/routers/agents.py`](../agent/routers/agents.py) `POST /agents/spawn` → `enqueue_threaded_autonomous` (`kind=tiny_agent`); poll [`GET /agent/tasks/{id}`](../agent/routers/agent.py); same store as background. |
| **Gap vs Claude** | No in-process nested `AgentTool` graph, no coordinator/teammate tool surface inside one JSON decision loop. |
| **Process isolation** | Optional subprocess worker (`background_use_subprocess_workers`) + `background_job_worker.py` — hard cancel; each worker may load its own GGUF (RAM cost) unless future LLM-delegation to parent. |
| **Suggested tests** | [`test_agents_spawn.py`](../agent/tests/test_agents_spawn.py), [`test_background_task_cancel.py`](../agent/tests/test_background_task_cancel.py), [`test_background_subprocess.py`](../agent/tests/test_background_subprocess.py) (sandbox + subprocess enqueue + `cancel_worker`). |
| **If full parity wanted** | Design doc: task DAG vs threads, caps, shared `conversation_id`, approval inheritance. |

---

## 3. FUTURE (not scheduled)

### Synthetic message on client abort mid-tool

**Status:** Implemented for streaming `POST /agent`: `client_abort_event` + `_inject_cancel_message` in [`agent_loop`](../agent/agent_loop.py); router watches `Request.is_disconnected()` (see [`PARITY_AUDIT.md`](PARITY_AUDIT.md)). Remaining gap: non-streaming `/agent` does not pass a disconnect signal (by design — no open SSE).

| | |
|---|---|
| **Optional hardening** | Propagate abort into long-running tool threads (subprocess kill) — not done; cooperative exit at decision-loop boundaries only. |
| **Suggested tests** | HTTP/SSE test with aborted `TestClient` stream; assert history or task record contains abort marker (once API defined). |

---

## 4. IMPLEMENTED — optional hardening tests

### Concurrent read-only tool batches

| | |
|---|---|
| **Parity row** | Concurrent read-only tool batches |
| **Code** | [`agent/agent_loop.py`](../agent/agent_loop.py) D1 block (~2890+): `decision["batch_tools"]` + `ThreadPoolExecutor`; [`agent/decision_schema.py`](../agent/decision_schema.py) parses `batch_tools`. |
| **Tests** | [`test_agent_loop_batch_tools.py`](../agent/tests/test_agent_loop_batch_tools.py): concurrent `read_file` + `list_dir`; asserts both ran and **primary-before-batch order** in `steps`. |

---

## 5. Reference repos (clean-room)

| Tree | Role | Layla integration |
|------|------|-------------------|
| `integrations/openclaude-main/` | Bun/TS Claude-like CLI + OpenAI-compat | Pattern only; no vendored runtime in `agent/`. |
| `claude-code-sourcemap-main/` (root or integrations) | TS CLI + permissions patterns | Pattern only; see [`integrations/README.md`](../integrations/README.md). |
| `claw-code-main/` | Python + Rust harness | [`PARITY.md`](../claw-code-main/PARITY.md) internal TS vs Rust gaps — checklist only. |

Do not copy source verbatim; implement behavior in Python with tests.

---

## 6. Doc / manifest hygiene

| Task | Owner |
|------|--------|
| Keep [`PARITY_AUDIT.md`](PARITY_AUDIT.md) status column in sync with this file | Humans + AI |
| Add new stable paths/symbols to [`parity_manifest.yaml`](parity_manifest.yaml) when claiming IMPLEMENTED | CI: `pytest agent/tests/test_parity_manifest.py` |
| Bump [`agent/tests/test_registered_tools_count.py`](../agent/tests/test_registered_tools_count.py) `EXPECTED_TOOL_COUNT` when adding tools | Required |
