# Architecture — One-Page Overview

> For the full AI operations manual (file map, rules, style guide), see **`AGENTS.md`**.

---

## Pinned versions and paths

- **Python**: 3.11+ (tested 3.11–3.12). Dependencies: `agent/requirements.txt`.
- **Database**: SQLite at **repo root** `layla.db`. All persistent memory (learnings, study_plans, wakeup_log, audit, aspect_memories, project_context, capabilities) lives here.
- **Config**: `agent/runtime_config.json` (gitignored). Template at `agent/runtime_config.example.json`.
- **Model**: `models/<filename>.gguf` (gitignored). Set `model_filename` in config.

---

## Request flow

```
Client
  → HTTP → FastAPI (agent/main.py, port 8000)
  → Router dispatch:
      /agent, /learn/          → routers/agent.py    → agent_loop.autonomous_run()
      /research_mission        → routers/research.py → agent_loop (research_mode=True)
      /study_plans, /wakeup    → routers/study.py
      /approve, /pending       → routers/approvals.py
      /voice/transcribe        → services/stt.py     (faster-whisper)
      /voice/speak             → services/tts.py     (kokoro-onnx)
      /health, /v1/*, /ui      → main.py (inline)
```

**agent_loop.autonomous_run():**
1. `runtime_safety.load_config()` — TTL-cached, hot-path safe
2. `orchestrator.select_aspect()` — keyword-based, loads `personalities/*.json`
3. `_build_system_head()` — identity + knowledge RAG (BM25+vector+FTS5+rerank) + learnings + CoT
4. **Decision loop** (up to `max_tool_calls`):
   - `_llm_decision()` → parse JSON `{action, tool_name, objective_complete, ...}`
   - If `action=tool`: `registry.TOOLS[name]()` — gated by `allow_write`/`allow_run` + approval
   - If `action=reason` or `objective_complete`: `_completion()` → stream final reply
5. Optional self-reflection (`enable_self_reflection`) — score + rewrite if < 7/10
6. `_save_outcome_memory()` — distill and store outcome

**Approval:** tool returns `approval_required` → queued in `shared_state.pending` → `POST /approve {"id": uuid}` → proceed

---

## Where state lives

| What | Where |
|---|---|
| Learnings, study plans, wakeup log, audit | SQLite `layla.db` (repo root) |
| FTS5 full-text search index | Virtual table in `layla.db` (auto-sync triggers) |
| Semantic memory vectors | ChromaDB `agent/chroma/` (config-driven) |
| BM25 index | In-memory, rebuilt from learnings on count change |
| Conversation history | `shared_state` in-memory deque |
| Pending approvals | `shared_state.pending` list + audit in DB |
| Knowledge index | ChromaDB `agent/chroma/` (collection: `knowledge`) |
| Research lab / output | `agent/.research_lab/`, `agent/.research_output/`, `agent/.research_brain/` |
| Config | `agent/runtime_config.json` |

---

## Scheduler and wakeup

- **Scheduler**: APScheduler background job advances study plans only when `touch_activity` is recent (touched by `/agent`, `/wakeup`, `/learn/`, `/ui`). Config: `scheduler_study_enabled`, `scheduler_interval_minutes`, `scheduler_recent_activity_minutes`.
- **Wakeup**: `GET /wakeup` marks activity, logs session, returns last wakeup time, active study plans, and optional "what was studied" summary.

---

## Key files

| File | Role |
|---|---|
| `agent/main.py` | FastAPI app, lifespan, all routes, `/ui`, `/v1`, `/health`, GZip middleware |
| `agent/agent_loop.py` | `autonomous_run()`, decision loop, tool dispatch, streaming, self-reflection |
| `agent/orchestrator.py` | Aspect selection, deliberation prompt builder |
| `agent/runtime_safety.py` | Config load (TTL-cached), file caching, hardware probe, sandbox validation |
| `agent/shared_state.py` | Shared refs: history deque, pending approvals, touch_activity, audit |
| `agent/decision_schema.py` | Pydantic decision model, `parse_decision()` |
| `agent/layla/tools/registry.py` | All 21 tools + `TOOLS` dict. Add tools here. |
| `agent/layla/memory/db.py` | SQLite schema, `migrate()`, all DB access, FTS5 |
| `agent/layla/memory/vector_store.py` | ChromaDB, BM25, cross-encoder reranking, HyDE, parent-doc retrieval |
| `agent/services/llm_gateway.py` | `run_completion()`, `prewarm_llm()`, auto-thread detection |
| `agent/services/stt.py` | faster-whisper STT |
| `agent/services/tts.py` | kokoro-onnx TTS with pyttsx3 fallback |
| `agent/services/browser.py` | Playwright browser automation |
| `agent/routers/agent.py` | `POST /learn/`, `POST /agent` |
| `agent/routers/approvals.py` | `POST /approve`, `GET /pending` |
| `agent/routers/study.py` | `GET /wakeup`, `/study_plans` |
| `agent/ui/index.html` | Web UI (also served embedded from main.py) |
| `personalities/*.json` | Aspect definitions. Loaded dynamically — never hardcode the list. |
