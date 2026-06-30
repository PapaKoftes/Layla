---
last_mapped_commit: dc0b9c0ad8bdb1cba9afea771ad54a55473ec14d
---
# Codebase Structure

**Analysis Date:** 2026-06-29

## Directory Layout

```text
Layla/                            # repo root (docs, installers, launchers, llama.cpp/)
├── layla.py / launcher.py        # top-level launch shims into agent/
├── transports/ integrations/     # discord_bot/, cursor-layla-mcp/, etc.
├── personalities/ skills/ plugins/ knowledge/
└── agent/                        # THE APPLICATION (everything runs from here)
    ├── main.py                   # FastAPI app: lifespan, middleware, 38 routers (930 ln)
    ├── agent_loop.py             # the orchestration spine (4119 ln)
    ├── serve.py / tui.py         # HTTP and terminal entry points
    ├── runtime_safety.py         # cached runtime_config.json loader
    ├── config_schema.py constants.py shared_state.py  # config + per-request state
    ├── orchestrator.py coordinator (via services) background_job_worker.py
    ├── research_*.py             # research lab / intelligence pipeline
    ├── routers/                  # 38 HTTP/WS/SSE routers (thin adapters)
    │   ├── agent.py              #   primary /agent chat stream entry
    │   ├── autonomous.py memory.py knowledge.py settings.py ws.py ...
    ├── services/                 # 203 flat capability modules
    │   ├── llm_gateway.py        #   single serialized completion gateway
    │   ├── inference_router.py   #   backend select: llama.cpp / Ollama / OpenAI
    │   ├── tool_dispatch.py      #   intent → tool, sandbox + approval (TRUST BOUNDARY)
    │   ├── planner.py model_router.py system_head_builder.py memory_router.py ...
    │   └── sandbox/              #   python_runner.py, shell_runner.py
    ├── layla/                    # reusable core package
    │   ├── memory/               #   SQLite db.py, migrations, graph, distill, conversations
    │   ├── tools/                #   registry.py + domains/ (12) + impl/ (tool bodies)
    │   ├── codex/                #   knowledge codex db + enricher + linker
    │   ├── geometry/ + cam/      #   machining IR, executor, feeds/speeds, simulator
    │   ├── scheduler/            #   idle detector, jobs, registry, activity
    │   ├── ingestion/            #   chunker, extractors, pipeline
    │   └── skills/  time_utils.py file_understanding.py
    ├── core/                     # executor.py, observer.py, validator.py
    ├── autonomous/               # planner, controller, policy, budget, retrieval, value_gate
    ├── schemas/                  # Pydantic requests.py, entity.py
    ├── ui/                       # static front end: index.html + 29 JS + css/ assets/ vendor/
    └── tests/                    # 204 test files (+ integration/ e2e_ui/ smoke/ fixtures/)
```

## Directory Purposes

**`agent/` (root of the app):**
- Process entry, the agent loop, config, and cross-cutting state. Run everything
  from here — top-level repo shims just `cd` into it.
- Key files: `main.py`, `agent_loop.py` (4119 ln), `runtime_safety.py`,
  `shared_state.py`.

**`agent/routers/` (38 modules):**
- HTTP/WebSocket/SSE surface. Thin adapters that parse requests and call the loop
  or a service. Wired in `main.py:550-647`.
- Key files: `agent.py` (chat), `autonomous.py`, `ws.py`, `openai_compat.py`.

**`agent/services/` (203 modules):**
- Flat capability catalog — the bulk of the system. Largest: `tool_dispatch.py`
  (1122 ln), `system_head_builder.py` (1086), `llm_gateway.py` (944),
  `planner.py` (937), `agent_task_runner.py` (897).
- Only nested package: `services/sandbox/` (subprocess runners).

**`agent/layla/` (core package):**
- Transport-agnostic domain logic, importable independent of FastAPI.
  - `memory/` — durable store (`db.py`), migrations, graph, distillation,
    conversations, RL preferences.
  - `tools/` — `registry.py` assembles `TOOLS` from `domains/` (12: file, web,
    code, git, system, memory, data, analysis, automation, geometry, general)
    and `impl/`.
  - `geometry/` + `cam/` — CAD/CAM machining (IR, executor, simulator, tool library).
  - `scheduler/`, `ingestion/`, `codex/`, `skills/`.

**`agent/ui/`:**
- Static PWA: `index.html`, 29 JS files in `js/` (`layla-app.js`, `chat.js`,
  `api.js`, `layla-autonomous.js`, ...), `css/`, `assets/`, `vendor/`, `sw.js`,
  `manifest.json`. Served via `StaticFiles` mounts in `main.py`.

**`agent/tests/`:**
- 204 top-level `test_*.py` plus `integration/` (6), `integration_smoke/` (4),
  `e2e_ui/` (3), `fixtures/`. `conftest.py` at `agent/conftest.py`.

## Key File Locations

**Entry Points:**
- `agent/main.py`: FastAPI app + router wiring.
- `agent/serve.py`, `agent/tui.py`: HTTP / terminal launchers.

**Configuration:**
- `agent/runtime_safety.py`: `load_config()` (cached, line 186).
- `agent/config_schema.py`: schema/hints for `runtime_config.json`.

**Core Logic:**
- `agent/agent_loop.py`: `autonomous_run` (2244), `stream_reason` (770).
- `agent/services/llm_gateway.py` + `inference_router.py`: the one model path.
- `agent/services/tool_dispatch.py`: tool execution + security boundary.

**Testing:**
- `agent/tests/`, `agent/conftest.py`.

## Naming Conventions

**Files:**
- snake_case modules. Services are flat single-purpose files
  (`memory_router.py`, `tool_policy.py`). UI JS is `layla-*.js` (kebab-case).

**Directories:**
- lowercase; the reusable package is `layla/`, the app shell is everything else
  under `agent/`.

## Where to Add New Code

**New HTTP/WS endpoint:**
- Add/extend a router in `agent/routers/`, then `app.include_router(...)` in
  `agent/main.py` (~line 550-647).

**New capability/service:**
- Add a module to `agent/services/` (flat). Call it from `agent_loop.py` or a
  router — do NOT grow `agent_loop.py`.

**New tool:**
- Implement the body in `agent/layla/tools/impl/`, register it in the matching
  `agent/layla/tools/domains/<domain>.py` dict; it merges via
  `layla/tools/registry.py`. Enforce sandbox/approval in
  `services/tool_dispatch.py` if it touches the filesystem.

**New reusable domain logic:**
- Add to the appropriate `agent/layla/<subpackage>/` (memory, geometry, codex,
  scheduler, ingestion).

**New UI feature:**
- Add a `layla-*.js` to `agent/ui/js/` and wire it from `index.html` /
  `layla-app.js`.

**Tests:**
- `agent/tests/test_*.py` for unit; `tests/integration/`, `tests/e2e_ui/`,
  `tests/integration_smoke/` for broader scopes.

**Config knob:**
- Add the key to `agent/config_schema.py` and read it via
  `runtime_safety.load_config()`.

## Special Directories

**`agent/__pycache__`, `*/__pycache__`:** generated, not committed.
**`llama.cpp/` (repo root):** vendored inference backend; not Layla source.
**`agent/models/`:** local GGUF model storage (runtime, not source).
**`.planning/`:** GSD planning artifacts (this directory).

---

*Structure analysis: 2026-06-29*
