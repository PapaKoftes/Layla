# AGENTS.md — AI Operations Manual for Layla

This file is for any AI assistant (Claude, GPT, Codex, Aider, Gemini, etc.) working on this repo.
Read this before touching any file. It tells you what this project is, where things live, what to keep updated, and what not to break.

---

## What this project is

Layla is a **self-hosted AI companion and engineering agent** that runs on the user's own hardware via a local GGUF model (llama-cpp-python). No cloud. No API keys required. She has six personality aspects, persistent memory (SQLite + ChromaDB), 109 registered tools, voice I/O, and browser automation. The FastAPI server lives at `localhost:8000`. The web UI is at `/ui`.

**The operator chooses their model.** Layla is uncensored by default. Everything is configurable via `agent/runtime_config.json`.

---

## Hard rules — never violate these

1. **Never commit `agent/runtime_config.json`** — it's gitignored and contains local paths + model name.
2. **Never commit anything in `knowledge/`** unless it has an explicit `!knowledge/filename.md` exception in `.gitignore`. Personal knowledge is local-only.
3. **Never commit `layla.db`** — user's private memory.
4. **Never hardcode paths**. Use `Path(__file__).resolve().parent` chains. Always `.expanduser().resolve()` on config paths from `runtime_config.json`.
5. **Never break the approval gate.** File writes (`write_file`, `apply_patch`) and code execution (`shell`, `run_python`) must remain gated by `allow_write`/`allow_run` + the approval flow.
6. **Personalities are loaded dynamically** from `personalities/*.json`. Never hardcode an aspect list — always use `_load_aspects()` from `orchestrator.py`. The `systemPromptAddition` field is the character voice — it IS injected into every system head when that aspect is active. Do not truncate it. The `role` field is just a short label for routing and display.
7. **The DB schema must migrate forward.** Add columns via `db.execute("ALTER TABLE ... ADD COLUMN IF NOT EXISTS ...")` in the `migrate()` function in `agent/layla/memory/db.py`. Never drop columns.
8. **Keep `ARCHITECTURE.md` and `docs/IMPLEMENTATION_STATUS.md` updated** when you change the request flow, add routes, or implement a section from `LAYLA_NORTH_STAR.md`.

---

## Repository map — where to find things

```
/ (repo root)
├── agent/                   # All Python runtime code
│   ├── main.py              # FastAPI app, lifespan, all routes, /ui, /v1, /health
│   ├── agent_loop.py        # Core: autonomous_run(), decision/tool/reason loop, streaming
│   ├── orchestrator.py      # Aspect selection, deliberation prompt builder
│   ├── runtime_safety.py    # Config load (TTL-cached), file caching, hardware probe
│   ├── shared_state.py      # Shared refs: history, pending approvals, touch_activity
│   ├── decision_schema.py   # Pydantic decision model, parse_decision()
│   ├── first_run.py         # Hardware wizard, writes runtime_config.json
│   │
│   ├── routers/             # FastAPI routers (mounted in main.py)
│   │   ├── agent.py         # POST /agent, POST /learn/
│   │   ├── approvals.py     # POST /approve, GET /pending
│   │   ├── study.py         # GET /wakeup, /study_plans
│   │   └── research.py      # Research mission endpoints
│   │
│   ├── services/            # Infrastructure services (singleton pattern)
│   │   ├── llm_gateway.py   # run_completion(), prewarm_llm(), auto-thread detection
│   │   ├── stt.py           # faster-whisper STT (transcribe_bytes, prewarm)
│   │   ├── tts.py           # kokoro-onnx TTS (speak_to_bytes, prewarm)
│   │   └── browser.py       # Playwright browser (navigate, search, screenshot, fill)
│   │
│   ├── layla/
│   │   ├── tools/
│   │   │   └── registry.py  # ALL tools live here + TOOLS dict. Add tools here.
│   │   ├── memory/
│   │   │   ├── db.py        # SQLite schema, migrate(), all DB access functions
│   │   │   ├── vector_store.py  # ChromaDB, BM25, cross-encoder, HyDE, parent-doc
│   │   │   └── distill.py   # Post-run memory distillation
│   │   └── file_understanding.py  # analyze_file()
│   │
│   ├── ui/index.html        # Standalone web UI (also served embedded from main.py)
│   ├── runtime_config.json  # GITIGNORED. Active config.
│   └── runtime_config.example.json  # Template with all keys documented
│
├── personalities/           # One JSON per aspect. Loaded dynamically.
│   ├── morrigan.json        # Engineer. Default aspect.
│   ├── nyx.json             # Researcher
│   ├── echo.json            # Companion/mirror
│   ├── eris.json            # Chaos/banter
│   ├── lilith.json          # Core/sovereign, NSFW register, will_refuse=false
│   └── cassandra.json       # Unfiltered oracle/reactive
│
├── .identity/               # GITIGNORED (except self_model.md). Lilith's deep self-model.
│   └── self_model.md        # Injected into system head only when Lilith is active.
│
├── knowledge/               # GITIGNORED by default. Place .md/.txt/.pdf for indexing.
│   └── (curated base docs are excepted in .gitignore)
│
├── models/                  # GITIGNORED. Put .gguf model files here.
│
├── cursor-layla-mcp/        # Cursor MCP server (chat_with_layla, add_learning, etc.)
│   └── server.py
│
├── AGENTS.md                # THIS FILE. Universal AI context.
├── LAYLA_NORTH_STAR.md      # Canonical vision §1–§20. Source of truth for features.
├── ARCHITECTURE.md          # One-page request flow + state map. Keep updated.
├── MODELS.md                # Model selection guide with HuggingFace links.
├── INSTALL.bat / install.sh # One-click installers
├── START.bat / start.sh     # One-click launchers
│
├── docs/
│   ├── IMPLEMENTATION_STATUS.md  # Maps NORTH_STAR §§ to code files. Keep updated.
│   ├── RUNBOOKS.md               # How to add tools, aspects, knowledge
│   ├── TECH_STACK_AND_CAPABILITIES.md
│   ├── ROADMAP.md / MILESTONES.md
│   └── REMOTE_ARCHITECTURE.md
│
└── .cursor/rules/
    ├── layla-assistant.mdc  # Cursor AI: aspects, MCP tools, approval flow (alwaysApply)
    └── north-star.mdc       # Cursor AI: North Star pointer + implementation status
```

---

## Request flow (concise)

```
Client → POST /agent → routers/agent.py
  → agent_loop.autonomous_run()
    → runtime_safety.load_config()        # TTL-cached, mtime-cached file reads
    → orchestrator.select_aspect()        # keyword-based, loads personalities/*.json
    → _build_system_head()                # identity + knowledge RAG + learnings + CoT
    → loop:
        _llm_decision() → parse JSON      # action: "tool" | "reason"
        if tool: registry.TOOLS[name]()   # gated by allow_write/allow_run + approval
        if reason: _completion() stream   # final LLM response, optional self-reflection
    → _save_outcome_memory()              # distill and store outcome
```

**Voice endpoints**: `POST /voice/transcribe` (bytes → text via faster-whisper), `POST /voice/speak` (text → WAV via kokoro-onnx)  
**Memory write**: `POST /learn/` → `db.add_learning()` + `vector_store.add_vector()`  
**Approval**: tool returns `approval_required` → stored in `shared_state.pending` → `POST /approve {"id": uuid}` → re-run

---

## Code style

- **Python 3.11+**. Type hints everywhere. `pathlib.Path` for all file ops.
- **FastAPI patterns**: `APIRouter`, `JSONResponse`, `StreamingResponse`. Async routes call `asyncio.to_thread()` for blocking work.
- **Services are singletons** with module-level globals and `threading.Lock`. Use the pattern in `llm_gateway.py` and `stt.py`.
- **DB access**: all SQLite via `db._conn()` context manager in `agent/layla/memory/db.py`. Never raw sqlite3 elsewhere.
- **Config**: always `runtime_safety.load_config()`. Never read `runtime_config.json` directly. Never hardcode config values.
- **Logging**: `logging.getLogger("layla")` everywhere. No `print()` in production paths.
- **Error handling**: catch specific exceptions. Use `try/except Exception: pass` only for optional features with a fallback.
- **No inline CSS or styles in Python**. UI is `agent/ui/index.html`.
- **Naming**: snake_case for everything Python. JSON keys in personality files are camelCase (`systemPromptAddition`, `nsfw_triggers`).

---

## How to add things

### Add a tool
1. Define function in `agent/layla/tools/registry.py`
2. Add to `TOOLS` dict: `"tool_name": {"fn": fn, "dangerous": bool, "require_approval": bool, "risk_level": "low"|"medium"|"high"}`
3. No restart needed if server reloads; otherwise restart.

### Add an aspect
1. Create `personalities/<id>.json` — required fields: `id`, `name`, `title`, `role`, `voice`, `systemPromptAddition`, `triggers`
2. Optional: `nsfw_triggers`, `systemPromptAdditionNsfw`, `color`, `tts_voice`, `decision_bias`
3. Restart Layla — aspects are glob-loaded at startup.

### Add a route
1. Add handler in the appropriate `agent/routers/*.py` (or `main.py` for one-off endpoints)
2. Mount in `main.py` lifespan or at module level for routers already included
3. Update `ARCHITECTURE.md` request flow section

### Add to the knowledge base
- Drop `.md`, `.txt`, or `.pdf` in `knowledge/`
- Add `!knowledge/filename.md` exception to `.gitignore` if it should be committed
- Layla re-indexes on startup when the directory fingerprint changes

---

## Living documents — keep these updated

| Document | Update when |
|---|---|
| `ARCHITECTURE.md` | Request flow changes, new routes, new state stores |
| `docs/IMPLEMENTATION_STATUS.md` | Any NORTH_STAR §§ are implemented or status changes |
| `agent/runtime_config.example.json` | New config keys added to `runtime_safety.py` defaults |
| `CHANGELOG.md` | Any commit worth noting for users |
| `docs/RUNBOOKS.md` | New "how to add X" procedures |

**Do NOT update** `LAYLA_NORTH_STAR.md` unless the user explicitly asks. It is the canonical vision document, not a status tracker.

---

## Common mistakes

| Mistake | Correct |
|---|---|
| `Path("~").resolve()` | `Path("~").expanduser().resolve()` |
| Hardcoding aspect list | `_load_aspects()` from `orchestrator.py` |
| Reading config directly | `runtime_safety.load_config()` |
| Blocking async route | `await asyncio.to_thread(blocking_fn)` |
| `ALTER TABLE ... ADD COLUMN` | Must be in `migrate()` in `db.py`, wrapped in try/except |
| Committing `runtime_config.json` | It's gitignored for a reason — local paths inside |
| `import json; open("runtime_config.json")` | Never. Use `runtime_safety.load_config()` |
| Adding `personalities/*.json` as hardcoded | Always dynamic: `glob("personalities/*.json")` |

---

## Testing

```bash
cd agent
pytest tests/ -x -q
```

Tests live in `agent/tests/`. Key test files: `test_agent_loop.py`, `test_north_star.py`, `test_approval_flow.py`, `test_sandbox.py`. CI runs on push via `.github/workflows/ci.yml`.

---

## Quick orientation for a new AI session

1. Read this file (done)
2. Read `ARCHITECTURE.md` for the request flow
3. Read `docs/IMPLEMENTATION_STATUS.md` to know what's implemented vs planned
4. Read the specific file you're about to change
5. Never change `LAYLA_NORTH_STAR.md` unless told to
