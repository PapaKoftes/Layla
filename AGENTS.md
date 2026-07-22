# AGENTS.md — AI Operations Manual for Layla

This file is for any AI assistant (Claude, GPT, Codex, Aider, Gemini, etc.) working on this repo.
Read this before touching any file. It tells you what this project is, where things live, what to keep updated, and what not to break.

---

## What this project is

> **Start with [.planning/PROJECT.md](.planning/PROJECT.md)** — the living project spine: core value,
> active requirements, explicit out-of-scope, constraints, and the key decisions that constrain
> future work. This file tells you HOW to work in the repo; PROJECT.md tells you WHAT and WHY.

Layla is a **self-hosted AI companion and engineering agent** that runs on the user's own hardware via a local GGUF model (llama-cpp-python). No cloud. No API keys required. She has six personality aspects, persistent memory (SQLite; optional ChromaDB — **usually absent, and RAG then silently falls back to SQLite FTS**, so do not assume vector search is live), **200 registered tools** (authoritative count: `agent/tests/test_registered_tools_count.py` → `EXPECTED_TOOL_COUNT`), voice I/O, and browser automation. The FastAPI server lives at `localhost:8000`. The web UI is at `/ui`.

**The operator chooses their model.** Layla is uncensored by default. Everything is configurable via `agent/runtime_config.json`.

---

## Start here (operators vs contributors)

| Goal | Path |
|------|------|
| Install and run today | [docs/GETTING_STARTED.md](docs/GETTING_STARTED.md) then [README.md](README.md) Install and **START.bat** / **start.sh** → `http://localhost:8000/ui` |
| Ten-minute acceptance | [docs/GOLDEN_FLOW.md](docs/GOLDEN_FLOW.md) — section **Ten-minute operator acceptance** |
| Sandbox + remote safety | [docs/OPERATOR_SANDBOX.md](docs/OPERATOR_SANDBOX.md), [docs/REMOTE_ARCHITECTURE.md](docs/REMOTE_ARCHITECTURE.md) |
| Approvals / diff / grants | [docs/OPERATOR_APPROVALS.md](docs/OPERATOR_APPROVALS.md) |
| Coding agent habits (spawn, MCP, approvals) | [docs/CODING_AGENT_WORKFLOW.md](docs/CODING_AGENT_WORKFLOW.md), [docs/PARITY_AUDIT.md](docs/PARITY_AUDIT.md) |
| Web UI QA rubric | [docs/WEB_UI_OPERATOR_RUBRIC.md](docs/WEB_UI_OPERATOR_RUBRIC.md) |
| CI / parity commands | [docs/VERIFICATION.md](docs/VERIFICATION.md) |

Contributors: continue with **Repository map** below; update [docs/IMPLEMENTATION_STATUS.md](docs/IMPLEMENTATION_STATUS.md) when you change request flow.

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
7. **The DB schema must migrate forward.** Add columns via `db.execute("ALTER TABLE ... ADD COLUMN IF NOT EXISTS ...")` inside `_migrate_impl()` in `agent/layla/memory/migrations.py` (loaded by `migrate()`). `db.py` is a barrel that re-exports `migrate` / `_conn`. Never drop columns.
8. **Keep `ARCHITECTURE.md` and `docs/IMPLEMENTATION_STATUS.md` updated** when you change the request flow, add routes, or implement a section from `docs/PRODUCT_VISION.md` *(note: `LAYLA_NORTH_STAR.md` is referenced in places but does not exist)*.
9. **Ethical AI** — All behavior must align with `docs/ETHICAL_AI_PRINCIPLES.md`. Never bypass approval, sandbox, or refusal.

---

## Repository map — where to find things

```
/ (repo root)
├── agent/                   # All Python runtime code
│   ├── main.py              # FastAPI app, lifespan, all routes, /ui, /v1, /health
│   ├── agent_loop.py        # Core: autonomous_run(), decision/tool/reason loop, streaming
│   ├── execution_state.py   # Dict-compatible ExecutionState factory + JSON helpers
│   ├── orchestrator.py      # Aspect selection, deliberation prompt builder
│   ├── runtime_safety.py    # Config load (TTL-cached); `LAYLA_DATA_DIR` → per-user `runtime_config.json`; `default_models_dir()`
│   ├── shared_state.py      # Shared refs: history, pending approvals, touch_activity
│   ├── decision_schema.py   # Pydantic decision model, parse_decision()
│   ├── first_run.py         # Hardware wizard, writes runtime_config.json
│   │
│   ├── routers/             # FastAPI routers (mounted in main.py)
│   │   ├── system.py        # /health, /usage, /debug/state, /debug/tasks, /version, /update/*, /doctor, /skills, …
│   │   ├── agent.py         # POST /agent (+ includes learn + agent_tasks routers)
│   │   ├── learn.py         # GET /memories, POST /schedule, POST /learn/
│   │   ├── agent_tasks.py   # /resume, /execute_plan, /agent/background, /agent/tasks*
│   │   ├── approvals.py     # POST /approve, GET /pending
│   │   ├── study.py         # GET /wakeup, /study_plans (includes v3 maturity fields + plan-report snippets)
│   │   ├── research.py      # Research mission endpoints
│   │   ├── plans.py         # GET/POST /plans, PATCH/approve/execute — SQLite layla_plans
│   │   ├── plan_file.py     # /plan/* — Pydantic file plans under `.layla_plans/` (optional parallel to SQLite)
│   │   ├── codex.py         # GET/PUT /codex/relationship + codex proposals (sandbox-gated)
│   │   ├── conversations.py # /conversations* (includes v3 tags endpoints)
│   │   ├── aspects.py       # GET /aspects/{aspect_id} — aspect character sheet (safe subset)
│   │   ├── journal.py       # /journal* — operator journal entries
│   │   ├── workspace.py     # /platform/*, /project_discovery, /workspace/awareness/refresh, /workspace/project_memory, /workspace/symbol_search, …
│   │   └── improvements.py  # /improvements* — self-improvement proposals (approval applies allowlisted instructions)
│   │
│   ├── services/            # Infrastructure services (singleton pattern)
│   │   ├── coordinator.py        # classify + run (HTTP entry) + dispatch_autonomous_run + optional task graph / parallel helpers
│   │   ├── prompt_builder.py     # Static/dynamic system-head core + decision tool ordering
│   │   ├── memory_consolidation.py  # Scheduled memory maintenance hooks
│   │   ├── worktree_manager.py   # Optional git worktree isolation
│   │   ├── otel_export.py        # Optional OpenTelemetry span helper
│   │   ├── agent_task_runner.py  # Background task queue, threaded/subprocess workers, task store
│   │   ├── outcome_writer.py # Post-run outcome memory, Echo aspect memories, patch extract, auto-learnings
│   │   ├── llm_gateway.py   # run_completion(), prewarm_llm(), auto-thread detection
│   │   ├── stt.py           # faster-whisper STT (transcribe_bytes, prewarm)
│   │   ├── tts.py           # kokoro-onnx TTS (speak_to_bytes, prewarm)
│   │   ├── browser.py       # Playwright browser (navigate, search, screenshot, fill)
│   │   ├── capability_discovery.py  # PyPI, GitHub, HuggingFace candidate scan
│   │   ├── benchmark_suite.py      # Latency, throughput, memory benchmarks
│   │   ├── dependency_recovery.py # Optional pip install (allowlisted) + structured missing-dep / GGUF hints
│   │   ├── sandbox_validator.py    # Import + benchmark before enabling capability
│   │   ├── performance_monitor.py  # Runtime metrics (tool latency, retrieval)
│   │   ├── engine_plans.py         # Plan step normalization, mirror into project_memory; run_plan_iteration / file-plan loop
│   │   ├── plan_schema.py          # Pydantic Plan / PlanStep for file-backed `.layla_plans/*.json`
│   │   ├── plan_service.py         # CRUD for `.layla_plans/` (separate from SQLite layla_plans)
│   │   ├── plan_executor.py        # execute_next_step + continuous loop for file plans
│   │   ├── plan_refinement.py      # Optional one-pass LLM tighten (file_plan_refinement_enabled)
│   │   ├── relationship_codex.py   # `.layla/relationship_codex.json`; optional inject via relationship_codex_inject_enabled
│   │   ├── auto_updater.py         # GitHub latest check + `git pull --ff-only` (dev trees)
│   │   └── release_updater.py      # Release ZIP merge into `agent/` when `LAYLA_DATA_DIR` set
│   │
│   ├── capabilities/        # Capability registry (vector_search, embedding, etc.)
│   │   └── registry.py     # Multiple impls per capability; dynamic selection
│   ├── layla/
│   │   ├── tools/
│   │   │   ├── registry.py # TOOLS assembly, validation, metrics wrap, re-exports
│   │   │   ├── registry_body.py  # Re-exports tool callables from impl/*.py
│   │   │   ├── sandbox_core.py   # Sandbox path, read-freshness, shell policy helpers
│   │   │   └── impl/             # Tool implementations by domain (file_ops, code, git, …)
│   │   ├── memory/
│   │   │   ├── db.py # Barrel: re-exports domain DB APIs + `_conn`, `migrate`, `_DB_PATH`, `_MIGRATED` (tests patch these)
│   │   │   ├── db_connection.py  # `_DB_PATH` (`LAYLA_DATA_DIR` / `layla.db` when set), `_conn()`
│   │   │   ├── migrations.py   # `migrate()`, `_migrate_impl()`, schema DDL
│   │   │   ├── learnings.py, plans_db.py, projects_db.py, tasks_db.py, conversations.py, …
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
├── launcher/                # Desktop launcher: `layla_launcher.py`, `layla.spec` (PyInstaller → layla.exe)
├── installer/               # Windows: see `installer/README.md` (`layla.iss`, `build_installer.ps1`, embedded python bundler)
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
 → services/coordinator.run(agent_loop.autonomous_run, …) → dispatch_autonomous_run(…)
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
- **DB access**: all SQLite via `db._conn()` from `agent/layla/memory/db.py` (re-export of `db_connection._conn`). Never raw sqlite3 elsewhere.
- **Config**: always `runtime_safety.load_config()`. Never read `runtime_config.json` directly. Never hardcode config values.
- **Logging**: `logging.getLogger("layla")` everywhere. No `print()` in production paths.
- **Error handling**: catch specific exceptions. Use `try/except Exception: pass` only for optional features with a fallback.
- **No inline CSS or styles in Python**. UI is `agent/ui/index.html`.
- **Naming**: snake_case for everything Python. JSON keys in personality files are camelCase (`systemPromptAddition`, `nsfw_triggers`).

---

## How to add things

### Add a tool
1. Define function in `agent/layla/tools/registry_body.py` (or a new module imported into it)
2. Register metadata in `agent/layla/tools/domains/<domain>.py` (`fn_key` if name differs)
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
| `docs/STRUCTURED_ENGINEERING_PARTNER.md` | Engineering pipeline contracts, modes, or terminology change |
| `docs/FABRICATION_IR_AND_TOOLCHAIN.md` | DXF→IR→G-code chain, machining_ir, or fabrication scope changes |
| `docs/POST_AGENT_RESPONSE_CONTRACT.md` | `POST /agent` response shapes (pipeline, plans, fast path) change |
| `docs/PRODUCTION_CONTRACT.md` | Caps, safety invariants, or observability guarantees change |
| `docs/GOLDEN_FLOW.md` | Request lifecycle, approval semantics, or cross-surface contracts change |
| `docs/RULES.md` | Repo conventions or forbidden patterns change |
| `docs/TASKS.md` | Optional: note release themes or cross-cutting backlog |
| `docs/RELEASE_CHECKLIST.md` | Release steps or CI matrix change |
| `docs/LAYLA_PREBUILT_PLATFORM.md` | Capability domains or prebuilt principles change |
| `agent/runtime_config.example.json` | New config keys added to `runtime_safety.py` defaults |
| `CHANGELOG.md` | Any commit worth noting for users |
| `docs/RUNBOOKS.md` | New "how to add X" procedures; background workers / shared inference / OS limits / containers |
| `docs/OPERATOR_PSYCHOLOGY_SOURCES.md` | Behavioral/psychology knowledge options, optional libraries, or non-clinical policy cross-links change |
| `docs/FABRICATION_ASSIST.md` | Fabrication assist package or `BuildRunner` integration changes |

**Values:** [VALUES.md](VALUES.md) — sovereignty, privacy, anti-surveillance, solidarity. All development aligns with these.

**Do NOT update** `docs/PRODUCT_VISION.md` *(note: `LAYLA_NORTH_STAR.md` is referenced in places but does not exist)* unless the user explicitly asks. It is the canonical vision document, not a status tracker.

---

## Engineering discipline — every rule below was earned by a specific failure

Read this before you write code or believe a measurement. These are not style preferences; each one
cost real debugging time, and several cost *weeks of a broken product that looked healthy*.

### 1. THE SIGNATURE DEFECT: "built well and never plugged in"

This codebase's characteristic failure is a **complete, correct component with no caller**, or a
callee that sets one field while the caller inspects another. Confirmed instances:

| What looked fine | What was true |
|---|---|
| Tool dispatch, fully implemented | The agent executed **zero tools for 16 days** — dispatch discarded the model's args |
| Conversation summariser, correct | **0 rows ever** — gated on a threshold a ring buffer cannot reach |
| Aspect memories, working | All filed under a hardcoded `"echo"`; 5 of 6 aspects had no memory |
| LAN clustering, every piece present | Nothing called it; moved zero work |
| SM-2 spaced repetition | Algorithm added, **still zero callers** |

**Therefore: existence is not evidence.** Before claiming a feature works, prove there is a CALLER on
a path a real user reaches — by AST, not by reading the file. `_handle_understand_file` read
`decision["args"]` correctly while `_handle_read_file`, three functions away, did not.

### 2. TESTS DO NOT PROVE THE PRODUCT WORKS HERE

4047 tests pass and **every one mocks the model.** A total product failure — zero tool executions,
confident fabrication of file contents — survived the entire suite *and* the product benchmark,
because every benchmark dimension scored the reply TEXT and none asked whether a tool ran.

- Green suite ≠ working product. **Live measurement or it did not happen.**
- Reproduction harness that bypasses HTTP and the response cache:
  `agent_loop.autonomous_run(goal)` directly.
- `response_cache_enabled` is **true** — an A/B test whose second sample is a cached replay is not
  an A/B test. This invalidated a real experiment mid-session.

### 3. VERIFY THE PROBE BEFORE THE RESULT

Every measurement error in the P13 work was a **broken probe, not broken code** — roughly ten of
them. The dangerous ones fail *open* and return a plausible lie:

- A mutation test whose anchor string wasn't in the file: the mutation never applied, the test
  "passed", and appeared to prove teeth it did not have.
- A probe that set `LAYLA_DATA_DIR` then called `load_config()` — silently got defaults.
- A head-content probe passing `aspect=None`, so persona markers read "MISSING" because nothing was
  loaded, not because they were truncated.
- A file-path comparison that could never match because ruff emits `\` and git emits `/`.

**Rules:** every probe asserts its own preconditions and fails loudly
(`assert n == 1, "PROBE BROKEN: ..."`). Print the path/config the probe actually **resolved**, never
the one you assume. Prove a test fails in the direction it claims to guard (mutate → red → restore).

### 4. NEVER `git grep` FOR AN INVARIANT SCAN, NEVER TEXT-SCAN FOR BEHAVIOUR

`git grep` only searches **tracked** files — a gate once passed green because the offending file was
untracked, and a slice shipped on it. And a text scan for `cmd.endswith(blocked)` matched the
*comment documenting the removed bug*. Use **ripgrep** for files, **AST** for what code does.

### 5. ONE OWNER PER RULE — never two copies

Two shell blocklists existed; the weaker one silently won whenever the stronger path was
unavailable, allowing `cmd.exe` while falsely blocking `mydd`. **Delete the duplicate; do not fix
it.** Config defaults currently have **four** sources (`runtime_safety` defaults,
`runtime_config.example.json`, `first_run.py`, `install/setup_profiles.py`) — when changing a
default, check which one actually wins for a fresh install.

### 6. ASSERT THE MAPPING, NOT THE SHAPE

Five tests covered the aspect-memory function and all five passed while it wrote every memory to the
wrong aspect — because each asserted only *that* a save happened, never *which key*. A mock that
records a call but never inspects its arguments proves the code ran, which is rarely the claim worth
testing. One of those tests had no assertion at all, only a comment where the check belonged.

### 7. MEASURE PERFORMANCE WITH ALTERNATING RUN ORDER

On this thermally variable laptop, a sequential sweep loads drift onto the last cell. A sequential
benchmark reported **+136%** where the truth was **+12.7%** — nearly killing a correct change. Use
3+ samples per condition, **interleaved**, and report the spread alongside the mean. Run-to-run noise
here is larger than most effects being measured.

### 8. SHIP IN VERTICAL SLICES — TRUTH BEFORE EXPOSURE

Every slice leaves a **working product** and adds or exposes something a user can see. Never surface
a feature in the UI before its data/behaviour is real — a visible-but-dead control is worse than an
absent one, because `if (el)` turns the failure into silence.

### 9. DO NOT `git checkout --` TO UNDO A MUTATION

If the fix underneath is uncommitted, that destroys it too. This happened; four tests then failed for
entirely the wrong reason. Restore mutations with the inverse edit, anchor-checked.

### 10. WHEN A GUARD BLOCKS YOU, IT IS USUALLY RIGHT

`agent_loop.py` is capped at 1000 lines by `test_architecture_boundaries`. It refused three attempts
to grow it, and forced a constant into `orchestrator.py` beside the function that consumes it — a
better home than the one first chosen. Do not raise a cap or delete a comment to buy a line.

---

## Common mistakes

| Mistake | Correct |
|---|---|
| Believing a feature works because the module exists | Prove a caller by AST, on a user-reachable path |
| Believing a green suite means the product works | Drive the real app; the suite mocks the model |
| `git grep` for a repo-wide invariant scan | `rg` (grep misses untracked files) or an AST walk |
| Text-scanning source to decide what code *does* | AST — comments about removed bugs will match |
| `Path("~").resolve()` | `Path("~").expanduser().resolve()` |
| Hardcoding aspect list | `_load_aspects()` from `orchestrator.py` |
| Reading config directly | `runtime_safety.load_config()` |
| Blocking async route | `await asyncio.to_thread(blocking_fn)` |
| `ALTER TABLE ... ADD COLUMN` | Must be in `_migrate_impl()` in `migrations.py`, wrapped in try/except |
| Committing `runtime_config.json` | It's gitignored for a reason — local paths inside |
| `import json; open("runtime_config.json")` | Never. Use `runtime_safety.load_config()` |
| Adding `personalities/*.json` as hardcoded | Always dynamic: `glob("personalities/*.json")` |

---

## Testing

```bash
cd agent
pytest tests/ -x -q
```

**Default unit/integration** (excludes slow + browser e2e + optional smokes — same as CI):

```bash
cd agent
pytest tests/ -m "not slow and not e2e_ui and not browser_smoke and not voice_smoke and not gpu_smoke"
```

**Deep verification** (nightly / manual): `.github/workflows/verify-deep.yml` — UI e2e, `browser_smoke`, `voice_smoke`, doctor JSON artifact. See `docs/VERIFICATION.md`.

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
2. **If resuming from prior AI session:** Read `docs/AI_HANDOFF_REPORT.md` for historical cumulative state; **latest session handoff (2026-04-02 — Web UI, `/health`, chat UX, integrations zips):** `docs/AI_HANDOFF_SESSION_2026-04-02.md`
3. Read `ARCHITECTURE.md` for the request flow
4. Read `docs/IMPLEMENTATION_STATUS.md` to know what's implemented vs planned
5. Read the specific file you're about to change
6. Never change `docs/PRODUCT_VISION.md` *(note: `LAYLA_NORTH_STAR.md` is referenced in places but does not exist)* unless told to
