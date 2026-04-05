# Layla vs [Claude Code Unpacked](https://ccunpacked.dev/) — alignment map

**Source:** Unofficial tour of Claude Code’s agent loop, tool surface, commands, and roadmap-adjacent ideas (analysis dated March 31, 2026 on the site). **Not affiliated with Anthropic.** We use it as a **pattern checklist**, not a mandate to clone proprietary UX.

**Companion docs:** [`PARITY_AUDIT.md`](PARITY_AUDIT.md) (implemented vs reference trees), [`PARITY_BACKLOG.md`](PARITY_BACKLOG.md) (remaining gaps).

---

## 1. Agent loop (Unpacked: Input → … → Hooks → Await)

| Unpacked stage | Layla equivalent | Notes |
|----------------|------------------|--------|
| Input / Message | `POST /agent`, MCP, CLI, TUI | Multi-surface; not only Ink/stdin |
| History | `conversation_id`, `shared_state`, DB session | Comparable intent |
| System | `_build_system_head()`, aspects, skills, RAG | Richer persona/skill injection |
| API / Tokens | `llm_gateway`, `inference_router`, Ollama option | Local GGUF vs cloud API |
| Tools? / Loop | `agent_loop.autonomous_run`, `decision_schema` | Same JSON tool/reason pattern |
| Render | Streaming SSE, JSON replies | ✅ |
| Hooks | `services/agent_hooks.py` — `agent_hooks` in `runtime_config` (`session_start`, `pre_tool`, `post_tool`); steer hints, telemetry, UX queue | ✅ gated (`hooks_require_allow_run` / `allow_run` for pre/post tool) |
| Await | Approvals, `client_abort_event` on stream disconnect | ✅ cooperative cancel |

**Hooks:** [`agent/runtime_config.example.json`](../agent/runtime_config.example.json) (`agent_hooks`, `agent_hooks_enabled`, `hooks_require_allow_run`); implementation [`agent/services/agent_hooks.py`](../agent/services/agent_hooks.py) (env: `LAYLA_HOOK_EVENT`, `LAYLA_TOOL`, `LAYLA_CONVERSATION_ID`, …).

---

## 2. Tool families (Unpacked categories → Layla)

### File operations

Unpacked: FileRead, FileEdit, FileWrite, Glob, Grep, NotebookEdit.  
**Layla:** Broad file/git/search tools in `layla/tools/registry.py` (read/write/list/glob/grep/patch/…). **Parity:** strong. **Notebooks:** `notebook_read_cells` / `notebook_edit_cell` (`nbformat`).

### Execution

Unpacked: Bash, PowerShell, REPL.  
**Layla:** `shell`, `run_python`, persistent `shell_session_*`. **Parity:** good on Unix; PowerShell is OS-dependent.

### Search & fetch

Unpacked: WebSearch, WebFetch, WebBrowser, ToolSearch.  
**Layla:** Browser automation, `fetch_url`, search tools, `list_tools` / `tool_recommend`. **Parity:** reasonable; “tool search” is not identical to CC’s discovery UX.

### Agents & tasks

Unpacked: Agent, Task*, Team*, ListPeers.  
**Layla:** `/agents/spawn`, `/agent/background`, task store, `POST /schedule` for deferred tool runs; **cancel** `POST /agent/tasks/{id}/cancel` / `DELETE /agent/tasks/{id}`; spawn/background responses echo **`allow_write`**, **`allow_run`**, **`workspace_root`**; **conversation-scoped** history via `conversation_id` (`shared_state.get_conv_history`). **Parity:** **partial** — no nested in-process agent graph, team primitives, or peer listing.

### Planning / worktrees

Unpacked: EnterPlanMode, worktree enter/exit, VerifyPlanExecution.  
**Layla:** `plan_mode` on API, planner + `execute_plan`, git tools. **Worktrees:** `git_worktree_add` / `git_worktree_remove` (sandboxed) + spawn with `workspace_root` pointing at worktree path.

### MCP

Unpacked: mcpList, resources, auth.  
**Layla:** `cursor-layla-mcp/` (server to Cursor); in-agent **`mcp_tools_call`**, **`mcp_list_mcp_tools`**, **`mcp_list_mcp_resources`**, **`mcp_read_mcp_resource`**, **`mcp_operator_auth_hint`** (operator OAuth guidance), `services/mcp_client.py`. Optional **`mcp_inject_tool_summary_in_decisions`** (TTL tool summary in `_llm_decision`). **Gap:** no in-agent OAuth handshake (by design); authenticate out-of-band.

### System / UX

Unpacked: AskUserQuestion, TodoWrite, SkillConfig, Cron*, etc.  
**Layla:** Approvals UI/API, skills loader, study plans, scheduled tool dispatch, extensive config. **Parity:** overlapping; different names.

### AskUserQuestion (Claude Code) → Layla

Claude’s structured **ask** maps to Layla’s **approval gate**: dangerous tools return `approval_required` with a payload; operators approve via `POST /approve`, Web UI Approvals panel, MCP `approve_action`, or CLI. Session-scoped allowlists: [`routers/approvals.py`](../agent/routers/approvals.py) + [`services/session_grants.py`](../agent/services/session_grants.py) (`save_for_session` / `sg-*` in UI).

---

## 3. Slash commands vs Layla surfaces

Claude Code uses **slash commands**; Layla uses **HTTP** (and UI/TUI/MCP). Use this table as a **rough migrator map** (not all CC commands have a 1:1 route).

| Claude Code style | Layla HTTP / surface |
|-------------------|----------------------|
| `/compact` | `POST /compact` ([`main.py`](../agent/main.py)) |
| `/ctx_viz` | `GET /ctx_viz` |
| `/memory` / context | `GET /session/stats`, `shared_state` history, `POST /learn/` |
| `/plan` | `plan_mode` on `POST /agent`; planner inside `agent_loop` |
| `/resume` | `POST /resume` ([`routers/agent.py`](../agent/routers/agent.py)) |
| `/session` / export | `GET /session/export`, `GET /history`, `GET /conversations/...` |
| `/files` / add-dir | Workspace roots, `project_context`, `POST /workspace/index` |
| `/summary` | Reasoning tree summary in agent JSON; `GET /wakeup` (study) |
| `/tasks` | `GET /agent/tasks`, `POST /agent/background`, `POST /agents/spawn`, cancel `POST /agent/tasks/{id}/cancel` or `DELETE /agent/tasks/{id}` |
| `/agents` / fast | `POST /agents/spawn`, schedule priority on `POST /agent` |
| `/review` / `/diff` / `/commit` | Git + file tools in registry; `/undo` |
| `/status` / `/usage` | `GET /health`, `GET /usage`, `GET /doctor` |
| `/mcp` | `mcp_client_enabled` + `mcp_stdio_servers`; tools `mcp_list_mcp_tools`, `mcp_tools_call`, resources tools, `mcp_operator_auth_hint` |
| `/hooks` | `agent_hooks` in `runtime_config.json` ([`services/agent_hooks.py`](../agent/services/agent_hooks.py)) |
| `/skills` | `GET /skills`, `skills/` repo, `markdown_skills` config |

Full route list: [`main.py`](../agent/main.py) and [`routers/`](../agent/routers/). See also [RUNBOOKS.md](RUNBOOKS.md) (pointer to this section).

---

## 4. “Hidden features” on Unpacked (ideas, not promises)

| Unpacked idea | Layla today | Optional next step |
|---------------|------------|---------------------|
| **Kairos** (persistent memory + background) | Study plans, `POST /agent/background`, SQLite + Chroma, distill | Dedicated “consolidation” scheduled job (config flag) |
| **UltraPlan** (long windows) | `max_runtime_seconds`, `research_max_runtime_seconds`, `plan_depth`, `reasoning_effort`, model routing | Raise caps per preset; document in `runtime_config.example.json` |
| **Coordinator + worktrees** | `POST /agents/spawn` + `workspace_root`; **`git_worktree_add` / `git_worktree_remove`** tools | Spawn workers with `workspace_root` pointing at a worktree path |
| **Bridge** (remote) | [REMOTE_ARCHITECTURE.md](REMOTE_ARCHITECTURE.md), MCP | — |
| **Daemon / `--bg`** | `POST /agent/background` | — |
| **UDS inbox** | **Deferred** (IPC between sessions) | Design doc only |
| **Auto-Dream** | Post-run distill / reflection in `agent_loop` | Surface in UI “last session insights”; optional cron `POST /schedule` |

---

## 5. What we should *not* chase blindly

- **Feature parity with a cloud-only product** undermines local-first value (privacy, no API rent).
- **Unreleased / flag-gated CC features** may never ship or may change; treat as inspiration only.
- **50+ tools vs 170+ tools** — raw count is meaningless without quality and policy; Layla optimizes for **breadth + governance**.

### Explicitly deferred (vs Unpacked / CC)

- **UDS / session-to-session sockets** — security and product scope; not implemented.
- **In-process nested agent graph + ListPeers** — use **spawn + worktrees** instead until a design exists.
- **Non-streaming HTTP cancel (sync `/agent`)** — no open connection to signal abort; streaming uses `client_abort_event`. Background/spawn: cooperative cancel when `background_use_subprocess_workers` is false; **hard process kill** when subprocess workers are enabled (`POST /agent/tasks/{id}/cancel` / `DELETE`).
- **MCP OAuth inside the agent** — use each server’s CLI/login; configure `mcp_stdio_servers` after auth.

---

## 6. Implemented improvements (tracking)

- **MCP:** `mcp_session_list_tools`, `mcp_list_mcp_tools`, `mcp_tools_call`, optional **`mcp_inject_tool_summary_in_decisions`** (TTL prompt block), **`resources/list` + `resources/read`** session helpers and registry tools.
- **Hooks:** [`agent/services/agent_hooks.py`](../agent/services/agent_hooks.py) — `agent_hooks` + `session_start` / `pre_tool` / `post_tool`.
- **Git worktrees:** `git_worktree_add`, `git_worktree_remove`.
- **Background cancel:** `POST /agent/tasks/{task_id}/cancel` (alias of `DELETE /agent/tasks/{task_id}`).
- **Notebooks (optional):** `nbformat` + `notebook_read_cells` / `notebook_edit_cell`.
- **Spawn / background API:** JSON echoes `allow_write`, `allow_run`, `workspace_root`, `worker_mode` (`thread` \| `subprocess`); optional **subprocess workers** (`background_use_subprocess_workers`) for OS-level isolation + hard cancel; [`agent/background_job_worker.py`](../agent/background_job_worker.py), [`agent/services/background_subprocess.py`](../agent/services/background_subprocess.py).

When you add major loop features, update **§1–§3** and [`PARITY_AUDIT.md`](PARITY_AUDIT.md).
