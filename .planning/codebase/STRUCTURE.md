# Codebase Structure

**Analysis Date:** 2026-06-30

## Directory Layout

```
Layla/
├── agent/                      # The application (run everything from here)
│   ├── serve.py                # Port-guarded server entrypoint
│   ├── main.py                 # FastAPI app: routers, lifespan, runtime gate
│   ├── agent_loop.py           # Top-level agent loop (910 lines, decomposed)
│   ├── orchestrator.py         # Aspect (personality) selection
│   ├── routers/                # ~40 FastAPI routers by domain
│   ├── services/               # 19 sub-packages + backward-compat shims
│   │   ├── agent/              # Decomposed loop phases
│   │   ├── llm/                # Inference, models (governor-aware gateway)
│   │   ├── memory/  context/   # Memory + context assembly
│   │   ├── planning/ reasoning/
│   │   ├── retrieval/ tools/ skills/
│   │   ├── safety/ governance/ sandbox/
│   │   ├── cluster/ personality/ prompts/
│   │   ├── observability/ infrastructure/
│   │   ├── user/ workspace/
│   │   └── *.py                # Flat files = shims → sub-packages
│   ├── ui/                     # ES-module browser frontend
│   │   ├── main.js             # Single <script type="module"> entry
│   │   ├── core/               # bus, state, actions, overlay, compat
│   │   ├── services/           # api, health, utils
│   │   ├── components/         # ~28 view modules
│   │   ├── css/                # Styles (aspect CSS vars)
│   │   ├── aspects/  assets/   # Aspect SVGs, sigils, patterns, sprites
│   │   └── vendor/             # Bundled fonts/js/css
│   ├── install/                # Provisioning: probe → recommend → download → first run
│   ├── core/                   # executor, observer, validator
│   ├── setup/                  # python_compat runtime gate
│   ├── schemas/  routers/      # Pydantic schemas / API
│   ├── docs/                   # adr/001-006, VISION.md, design docs
│   └── tests/                  # Test suite
├── docs/                       # Project-wide docs incl. design/00-13
├── installer/  install/  launcher/   # OS install helpers + launchers
├── personalities/              # Aspect definitions
├── skills/ skill_packs/ plugins/
├── integrations/ transports/ discord_bot/ cursor-layla-mcp/
├── models/                     # Local model files
├── layla.db                    # SQLite store
└── pyproject.toml              # Package metadata + tooling
```

## Directory Purposes

**`agent/`** — The whole application. Run `serve.py`/`main.py` from inside `agent/`.

**`agent/services/`** — Domain logic in 19 sub-packages. The flat `*.py` files
are **backward-compat shims** (`sys.modules[__name__] = _real`); real code is in
the sub-package of the same-named module. See ARCHITECTURE.md for the mapping.

**`agent/services/agent/`** — Decomposed agent loop phases: `decision_loop.py`,
`stream_handler.py`, `reasoning_handler.py`, `tool_guards.py`,
`verification_engine.py`, `run_setup.py`, `run_finalizer.py`, `ux_emitter.py`.

**`agent/routers/`** — One module per API domain; all wired in `main.py` via
`include_router`.

**`agent/ui/`** — ES-module frontend. `core/` holds the bus/state/actions
infrastructure; `components/` are views; `aspects/` + `assets/` hold per-aspect
SVGs and palettes that re-theme the shell.

**`agent/install/`** — Install/provisioning system: `hardware_probe.py`,
`model_recommender`/`model_selector.py`, `model_downloader.py`,
`provision_model.py`, `run_first_time.py`, `setup_wizard.py`, `packs/`.

**`agent/docs/`** — `adr/001-006`, `VISION.md` (companion-first 10-phase plan).

## Key File Locations

**Entry Points:**
- `agent/serve.py`: port-guarded launch (run from `agent/`).
- `agent/main.py`: FastAPI `app` + lifespan.
- `agent/agent_loop.py`: agent run orchestration.

**Configuration:**
- `agent/runtime_config.json` (+ `.example.json`), `agent/config_schema.py`, `agent/runtime_safety.py`.
- `pyproject.toml`, `agent/requirements*.txt`.

**Core Logic:**
- Inference: `agent/services/llm/llm_gateway.py`.
- Governor: `agent/services/infrastructure/resource_governor.py`.
- Aspect selection: `agent/orchestrator.py`.

**Frontend:**
- `agent/ui/main.js`, `agent/ui/core/{bus,state,actions}.js`, `agent/ui/components/aspect.js`.

**Testing:**
- `agent/tests/`, `agent/conftest.py`, `agent/pytest.ini`.

## Naming Conventions

**Files:** snake_case Python modules; kebab/lowercase `.js` for UI components.
**Sub-packages:** lowercase domain nouns (`llm`, `memory`, `safety`).
**Shims:** flat `services/<name>.py` mirrors `services/<pkg>/<name>.py`.

## Where to Add New Code

**New service logic:**
- Implementation: `agent/services/<sub-package>/<module>.py` (the real module).
- Keep/create a flat shim `agent/services/<module>.py` only if legacy import
  paths must keep working; never put logic in the shim.

**New agent-loop phase:**
- `agent/services/agent/<phase>.py`; call it from `agent_loop.py` /
  `services/agent/decision_loop.py`. Do not inline into `agent_loop.py`.

**New API endpoint:**
- New/edit router in `agent/routers/<domain>.py`; register in `agent/main.py`.

**New UI view:**
- Component in `agent/ui/components/<name>.js`; import via `main.js`; use the
  `core/bus.js` + `core/state.js` patterns; read aspect CSS vars for theming.

**New aspect (personality):**
- Definition in `personalities/`; palette + SVG in `agent/ui/components/aspect.js`
  and `agent/ui/aspects/` / `agent/ui/assets/sigils/`.

**Install/provisioning step:**
- Module under `agent/install/`.

**Tests:**
- `agent/tests/` mirroring the module path.

## Special Directories

**`agent/services/` flat files** — Shims; generated by the refactor; committed.
**`agent/ui/vendor/`** — Bundled third-party assets; committed; do not hand-edit.
**`models/`, `layla.db`** — Local model files / runtime SQLite store; committed
state varies (large binaries usually gitignored).
**`.planning/`** — GSD planning artifacts (this map lives here).

---

*Structure analysis: 2026-06-30*
