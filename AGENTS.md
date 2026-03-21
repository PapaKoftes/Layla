# AGENTS.md — AI Operations Manual for Layla

This file is for any AI assistant (Claude, GPT, Codex, Aider, Gemini, etc.) working on this repo.
Read this before touching any file. It tells you what this project is, where things live, what to keep updated, and what not to break.

---

## What this project is

Layla is a **self-hosted AI companion and engineering agent** that runs on the user's own hardware via a local GGUF model (llama-cpp-python). No cloud. No API keys required. She has six personality aspects, persistent memory (SQLite + ChromaDB), 109 registered tools, voice I/O, and browser automation. The FastAPI server lives at `localhost:8000`. The web UI is at `/ui`.

**The operator chooses their model.** Layla is uncensored by default. Everything is configurable via `agent/runtime_config.json`.

---

## PREBUILT CAPABILITY PRINCIPLE

Layla should prioritize **integrated capabilities** — core features (conversation, knowledge, code, automation, model management, agent runtime, skills, hardware, self-improvement, UI) ship in the main install, not as optional plugins.

- **Minimal setup** — One install script (`INSTALL.bat` / `install.sh`), hardware wizard, model selection. Users should not manually install large numbers of plugins to get a working companion.
- **Human usability** — Clear UI, approval flow, aspect selection, voice I/O. Design for operators and everyday users, not just developers.
- **Hardware-aware defaults** — Model recommender, `n_ctx`, `n_gpu_layers`, acceleration backend. `first_run.py` and `runtime_safety` derive defaults from detected hardware.
- Avoid designs that require users to manually install many plugins. Prefer promoting optional dependencies to core when they materially improve the default experience.

See [docs/LAYLA_PREBUILT_PLATFORM.md](docs/LAYLA_PREBUILT_PLATFORM.md) for the full capability domain architecture.

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
9. **Ethical AI** — All behavior must align with `docs/ETHICAL_AI_PRINCIPLES.md`. Never bypass approval, sandbox, or refusal.

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
│   │   ├── browser.py       # Playwright browser (navigate, search, screenshot, fill)
│   │   ├── capability_discovery.py  # PyPI, GitHub, HuggingFace candidate scan
│   │   ├── benchmark_suite.py      # Latency, throughput, memory benchmarks
│   │   ├── dependency_recovery.py # Optional pip install (allowlisted) + structured missing-dep / GGUF hints
│   │   ├── sandbox_validator.py    # Import + benchmark before enabling capability
│   │   └── performance_monitor.py  # Runtime metrics (tool latency, retrieval)
│   │
│   ├── capabilities/        # Capability registry (vector_search, embedding, etc.)
│   │   └── registry.py     # Multiple impls per capability; dynamic selection
│   ├── layla/
│   │   ├── tools/
│   │   │   └── registry.py  # ALL tools live here + TOOLS dict. Add tools here.
│   │   ├── memory/
│   │   │   ├── db.py        # SQLite schema, migrate(), all DB access functions
│   │   │   ├── vector_store.py  # ChromaDB, BM25, cross-encoder, HyDE, parent-doc
│   │   │   └── distill.py   # Post-run memory distillation
│   │   ├── geometry/        # Structured CAD-like programs (schema, executor, backends)
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
├── fabrication_assist/      # Fabrication assist utilities (NOT imported by agent on main)
│   ├── assist/              # session, variants, explain, BuildRunner stub, layla_lite.assist(), CLI
│   └── README.md            # adapter pattern + usage; see docs/FABRICATION_ASSIST.md
│
├── cursor-layla-mcp/        # Cursor MCP server (chat_with_layla, add_learning, etc.)
│   └── server.py
│
├── AGENTS.md                # THIS FILE. Universal AI context.
├── PROJECT_BRAIN.md         # Stable system summary (read before deep repo scans).
├── LAYLA_NORTH_STAR.md      # Canonical vision §1–§20. Source of truth for features.
├── ARCHITECTURE.md          # One-page request flow + state map. Keep updated.
├── MODELS.md                # Model selection guide with HuggingFace links.
├── INSTALL.bat / install.sh # One-click installers
├── START.bat / start.sh     # One-click launchers
│
├── docs/
│   ├── IMPLEMENTATION_STATUS.md  # Maps NORTH_STAR §§ to code files. Keep updated.
│   ├── PRODUCTION_CONTRACT.md    # Operator guarantees: caps, safety, /health, logging
│   ├── RULES.md                  # Naming, layout, allowed/forbidden patterns (AI + humans)
│   ├── TASKS.md                  # Lightweight backlog pointer (avoid rot)
│   ├── RELEASE_CHECKLIST.md      # Pre-publish verification (tests, UI, MCP, CLI)
│   ├── RUNBOOKS.md               # How to add tools, aspects, knowledge
│   ├── TECH_STACK_AND_CAPABILITIES.md
│   ├── ROADMAP.md / MILESTONES.md
│   ├── REMOTE_ARCHITECTURE.md
│   └── FABRICATION_ASSIST.md     # Assist vs deterministic kernel; stub runner; integration checklist
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
    → _build_system_head()                # identity + knowledge RAG + learnings + CoT + optional anti-drift block (`anti_drift_prompt_enabled`)
    → loop:
        _llm_decision() → parse JSON      # action: "tool" | "reason"
        if tool: registry.TOOLS[name]()   # gated by allow_write/allow_run + approval
        if reason: _completion() stream   # final LLM response, optional self-reflection
    → _save_outcome_memory()              # distill and store outcome
```

**Voice endpoints**: `POST /voice/transcribe` (bytes → text via faster-whisper), `POST /voice/speak` (text → WAV via kokoro-onnx)  
**Memory write**: `POST /learn/` → `db.save_learning()` + `vector_store.add_vector()` (optional JSON `tags` for learnings)
**Config presets**: `POST /settings/preset` with `{"preset":"potato"}` merges schema keys into `runtime_config.json`
**Dual voice depth**: `POST /agent` optional `persona_focus` (second aspect id) merges into system head; primary `aspect_id` unchanged  
**Approval**: tool returns `approval_required` → stored in `shared_state.pending` → `POST /approve {"id": uuid}` → re-run

---

## Code style

- **Python 3.11 or 3.12** (3.13+ unsupported until explicitly tested; see `pyproject.toml` / `.python-version`). Type hints everywhere. `pathlib.Path` for all file ops.
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
| `docs/MODULE_SWEEP_TEMPLATE.md` / `docs/MODULE_SWEEP_STATUS.md` | New subsystem sweep doc or status row for a major area |
| `PROJECT_BRAIN.md` | Top-level shape, doc roles, or pinned facts change |
| `docs/IMPLEMENTATION_STATUS.md` | Any NORTH_STAR §§ are implemented or status changes |
| `docs/PRODUCTION_CONTRACT.md` | Caps, safety invariants, or observability guarantees change |
| `docs/GOLDEN_FLOW.md` | Request lifecycle, approval semantics, or cross-surface contracts change |
| `docs/RULES.md` | Repo conventions or forbidden patterns change |
| `docs/TASKS.md` | Optional: note release themes or cross-cutting backlog |
| `docs/RELEASE_CHECKLIST.md` | Release steps or CI matrix change |
| `docs/LAYLA_PREBUILT_PLATFORM.md` | Capability domains or prebuilt principles change |
| `agent/runtime_config.example.json` | New config keys added to `runtime_safety.py` defaults |
| `CHANGELOG.md` | Any commit worth noting for users |
| `docs/RUNBOOKS.md` | New "how to add X" procedures |
| `docs/OPERATOR_PSYCHOLOGY_SOURCES.md` | Behavioral/psychology knowledge options, optional libraries, or non-clinical policy cross-links change |
| `docs/FABRICATION_ASSIST.md` | Fabrication assist package or `BuildRunner` integration changes |

**Values:** [VALUES.md](VALUES.md) — sovereignty, privacy, anti-surveillance, solidarity. All development aligns with these.

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

**Default unit/integration** (excludes slow + browser e2e — same as CI):

```bash
cd agent
pytest tests/ -m "not slow and not e2e_ui"
```

**Playwright UI e2e** (Chromium; needs extra deps):

```bash
cd agent
pip install -r requirements-e2e.txt
python -m playwright install chromium
pytest tests/e2e_ui/ -m e2e_ui
```

If Playwright is not installed, `e2e_ui` tests are **skipped** (not failed).

Tests live in `agent/tests/`. Key test files: `test_agent_loop.py`, `test_north_star.py`, `test_approval_flow.py`, `test_sandbox.py`. CI runs on push via `.github/workflows/ci.yml`.

---

## Quick orientation for a new AI session

1. Read **`PROJECT_BRAIN.md`** (stable summary), then this file (`AGENTS.md`). Deep dives live under `docs/*_MODULE_SECOND_SWEEP.md`, indexed by **`docs/MODULE_SWEEP_STATUS.md`**.
2. **If resuming from prior AI session:** Read `docs/AI_HANDOFF_REPORT.md` for total state
3. Read `ARCHITECTURE.md` for the request flow
4. Read `docs/IMPLEMENTATION_STATUS.md` to know what's implemented vs planned
5. Read the specific file you're about to change
6. Never change `LAYLA_NORTH_STAR.md` unless told to
