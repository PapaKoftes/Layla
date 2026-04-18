# Tech Stack & Capabilities

Single reference for **technologies in use** and **current vs planned capabilities**. Update this doc when you add or remove components.

---

## Tech stack

| Layer | Technology | Notes |
|-------|------------|--------|
| **Runtime** | Python 3.11–3.12 | Supported on 3.11–3.12 (see `pyproject.toml` `requires-python`). See [README](../README.md#pinned-versions-and-paths). |
| **Server** | FastAPI | `agent/main.py`; mounts routers for agent, study, research, approvals. |
| **LLM** | llama-cpp-python | Loads GGUF models. No cloud dependency for core chat/agent. |
| **Database** | SQLite | Single file: repo root `layla.db`. Learnings, study plans, wakeup, audit, aspect memories, project context. |
| **Vector store** | Chroma (optional) | When `use_chroma: true`, indexes `knowledge/` (`.md`, `.txt`, `.pdf` with pypdf). Used for RAG. |
| **Embeddings** | sentence-transformers | For Chroma. Model configurable. |
| **Scheduler** | APScheduler | Optional background study when recent activity; config-driven. |
| **CLI** | layla.py | Wakeup, ask, study, plans, approve, export, pending, tui. |
| **TUI** | Textual | `agent/tui.py` — chat, wakeup, approve, aspect switch. |
| **MCP** | user-jinx server | Cursor integration: chat_with_layla, add_learning, start_study_session, etc. |

Config: `agent/runtime_config.json` (+ hardware-derived defaults in `runtime_safety.py`).

---

## Current capabilities

| Area | What’s implemented |
|------|---------------------|
| **Agent** | Local GGUF via llama-cpp-python; tool loop (read_file, write_file, list_dir, grep_code, glob_files, git_*, shell, run_python, apply_patch, fetch_url, file_info); approval gate for write/shell/run_python/patch; aspect selection (Morrigan, Nyx, Echo, Eris, Lilith, Cassandra); Lilith NSFW by keyword; optional deliberation; streaming. |
| **Memory** | SQLite `layla.db` (learnings, study plans, wakeup log, audit, aspect memories, project context); optional Chroma over `knowledge/`; conversation history in-memory + persisted. |
| **RAG** | Chroma indexes `knowledge/` (.md, .txt, optional .pdf with pypdf); top-k chunks in prompt; API returns `cited_sources` with answers. |
| **Study** | Study plans in DB; wakeup greeting; optional one autonomous study step per wakeup; scheduler advances one plan when user is active (configurable). |
| **Research** | Read-only agent run; research missions with staged pipeline (mapping → investigation → verification → distillation → synthesis); lab under `agent/.research_lab/`; brain files under `agent/.research_brain/`. |
| **Approvals** | Pending list; approve via API, CLI, TUI, Web UI; audit log. |
| **API** | `/agent`, `/learn/`, `/wakeup`, `/study_plans`, `/pending`, `/approve`, `/research`, `/research_mission`, `/system_export`, `/health`, OpenAI-compatible `/v1/chat/completions`, `/ui`. |
| **Remote** | Optional remote trigger (wakeup, one-shot) with API key auth; design in [REMOTE_ARCHITECTURE](REMOTE_ARCHITECTURE.md). |
| **Observability** | Optional `trace_id_enabled` → `X-Trace-Id` on responses. |

---

## Planned / optional capabilities

| Area | Plan |
|------|------|
| **Doc loaders** | Notion: export to Markdown and add under `knowledge/` (or future Notion API loader). PDF: done (optional pypdf). |
| **Research** | Extra stages or depth options as needed; refine stop/retry behavior. |
| **Initiative** | Optional discovery one-liner in wakeup (`wakeup_include_discovery_line`); already implemented. |
| **Tracing** | Optional structured logging or export (privacy-preserving) — backlog. |

---

## Key files (pointers)

- **App & routes**: `agent/main.py`
- **Agent loop**: `agent/agent_loop.py`
- **Config & safety**: `agent/runtime_safety.py`
- **Aspects**: `agent/orchestrator.py`, `personalities/*.json`
- **Memory DB**: `agent/jinx/memory/db.py`
- **Vector/RAG**: `agent/jinx/memory/vector_store.py`
- **Research pipeline**: `agent/research_stages.py`, `agent/routers/research.py`

For extension instructions: [RUNBOOKS](RUNBOOKS.md). For product roadmap: [ROADMAP](ROADMAP.md).
