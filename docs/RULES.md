# Repository rules — Layla

Binding conventions for **humans and AI agents** working on this repo. Stricter detail lives in **`AGENTS.md`** (operations manual) and **`docs/ETHICAL_AI_PRINCIPLES.md`**.

---

## Layout (there is no top-level `src/`)

| Area | Path |
|------|------|
| Application / runtime | **`agent/`** (FastAPI app, services, routers, tools, UI) |
| Personalities | `personalities/*.json` |
| Docs | `docs/` |
| Tests | **`agent/tests/`** |
| Root contracts | `PROJECT_BRAIN.md`, `ARCHITECTURE.md`, `AGENTS.md`, `LAYLA_NORTH_STAR.md` |

---

## Naming

- **Python**: `snake_case` for modules, functions, variables.
- **Types**: prefer explicit type hints (Python 3.11+).
- **JSON personalities**: `camelCase` for keys such as `systemPromptAddition`, `nsfw_triggers`.
- **Config keys** (`runtime_config.json`): `snake_case` as in `runtime_config.example.json`.

---

## Coding style

- Follow **`AGENTS.md`** code style (pathlib, `load_config()`, `logging.getLogger("layla")`, etc.).
- Run **`ruff`** and **`pytest`** before merge (see **`.github/workflows/ci.yml`** and `docs/RELEASE_CHECKLIST.md`).

---

## Allowed patterns

- Load config only via **`runtime_safety.load_config()`**.
- Resolve paths with **`Path(...).expanduser().resolve()`** where user home or config paths appear.
- Add tools in **`agent/layla/tools/registry.py`** and register in **`TOOLS`** with accurate `dangerous` / `require_approval` / `risk_level`.
- Add DB columns only through **`migrate()`** in **`agent/layla/memory/db.py`** (`ADD COLUMN`, never drop).
- Keep approval gates for writes and execution; never bypass for “convenience.”

---

## Forbidden patterns

- Commit **`agent/runtime_config.json`**, **`layla.db`**, or personal **`knowledge/`** without an explicit `.gitignore` exception.
- Hardcode absolute machine paths (use repo-relative chains from `Path(__file__)`).
- Hardcode the aspect list (use **`orchestrator`** / `_load_aspects()`).
- Read **`runtime_config.json`** directly instead of **`load_config()`**.
- Truncate **`systemPromptAddition`** in personality JSON (full text must be injected when that aspect is active).
- Introduce large refactors or new architectural patterns **inconsistent** with existing code without explicit maintainer intent.
- **AI drift**: avoid unnecessary new files, full-file rewrites, and one-off patterns — prefer minimal diffs (**`anti_drift_prompt_enabled`** in config mirrors this for the live agent).

---

## AI agents (Cursor, etc.)

1. Read **`PROJECT_BRAIN.md`**, then **`AGENTS.md`**.
2. Align with **`LAYLA_NORTH_STAR.md`** (do not edit unless the operator asks).
3. Check **`docs/IMPLEMENTATION_STATUS.md`** and **`docs/PRODUCTION_CONTRACT.md`** before changing behavior that affects safety or cost caps.
4. Update **`PROJECT_BRAIN.md`** when top-level shape or doc roles change; update **`ARCHITECTURE.md`** / **`docs/IMPLEMENTATION_STATUS.md`** when request flow or mapped features change.
