# PROJECT_BRAIN — Layla (stable system summary)

**Purpose:** One place to load **context before** scanning the whole tree. Use this with **`AGENTS.md`** (full manual), **`ARCHITECTURE.md`** (flow), and **`docs/RULES.md`** (conventions). For a **ground-truth technical audit** (gaps, risks, route inventory), see **`docs/FULL_TECHNICAL_AUDIT.md`**. Update this file when the *shape* of the system changes (major routes, layout, or doc roles)—not every small commit.

---

## What this repo is

**Layla** is a **local-first**, **planning-first** AI companion and engineering agent: FastAPI on **localhost:8000**, **Web UI** at **`/ui`**, optional **MCP** (`cursor-layla-mcp/`). Core loop: **`POST /agent`** → **`agent/agent_loop.autonomous_run()`** → LLM decisions → tools (gated) → streaming reply. **Plans:** durable **`layla_plans`** in SQLite + **`/plans`** API; optional file-backed **`/plan/*`** (`.layla_plans/*.json`, Pydantic steps); optional **`planning_strict_mode`** so mutating tools require an **approved** bound plan (default off). **Optional engineering pipeline** (config **`engineering_pipeline_enabled`**): modes **`chat` / `plan` / `execute`** with blocking clarifier, forced critics, refiner overwrite, governed execute, mandatory validator in execute mode — see **`docs/STRUCTURED_ENGINEERING_PARTNER.md`** and North Star **§21**. **Tools:** **189** registered in **`layla.tools.registry.TOOLS`** (authoritative count: **`EXPECTED_TOOL_COUNT`** in **`agent/tests/test_registered_tools_count.py`**). Six **aspects** load from **`personalities/*.json`** (never hardcode the list). **Memory:** SQLite **`layla.db`** + optional Chroma; **config:** **`agent/runtime_config.json`** (gitignored), template **`agent/runtime_config.example.json`**.

---

## Non-negotiables (read first)

| Rule | Where |
|------|--------|
| File map, how to add tools/routes/aspects | **`AGENTS.md`** |
| Vision / scope (canonical, rarely edit) | **`LAYLA_NORTH_STAR.md`** |
| Code ↔ North Star status | **`docs/IMPLEMENTATION_STATUS.md`** |
| Cost caps, `/health`, logging, safety mapping | **`docs/PRODUCTION_CONTRACT.md`** |
| Naming, layout, allowed/forbidden edits | **`docs/RULES.md`** |
| Backlog pointer (keep thin) | **`docs/TASKS.md`** |
| Ethics / refusal framing in product | **`docs/ETHICAL_AI_PRINCIPLES.md`** |

**Never commit:** `agent/runtime_config.json`, `layla.db`, personal `knowledge/` (unless explicitly excepted in `.gitignore`). **Shipped onboarding text:** `knowledge/starter/*.md` (curated, no personal data).

---

## Pinned technical facts

- **Python:** **3.11 or 3.12** (`pyproject.toml`, CI). Dependencies: **`agent/requirements.txt`**.
- **Entry:** **`agent/main.py`** (lifespan, middleware, UI/static; most HTTP routes in **`agent/routers/`**).
- **Core loop:** **`agent/agent_loop.py`**; config **`agent/runtime_safety.py`**; tools **`agent/layla/tools/registry.py`** + **`agent/layla/tools/impl/*.py`**. **SQLite:** **`layla/memory/migrations.py`** (schema) + domain modules (`learnings.py`, `plans_db.py`, …) re-exported from **`layla/memory/db.py`**. **Background tasks:** **`services/agent_task_runner.py`**; HTTP surface split as **`routers/learn.py`** + **`routers/agent_tasks.py`** (included from **`routers/agent.py`**).
- **Tests:** **`agent/tests/`** — `cd agent && python -m pytest tests/ -q` (CI uses `-m "not slow"`).
- **Observability:** **`GET /health`** — `model_loaded`, `model_routing`, `knowledge_index_*`, `effective_limits`, `cache_stats`, `response_cache_stats`.
- **Anti–AI drift (runtime prompt):** config **`anti_drift_prompt_enabled`** (default on) injects minimize-change instructions in **`_build_system_head()`**.
- **Fabrication assist (V1 infra):** root **`fabrication_assist/assist/`** — Pydantic schemas, typed errors, **`StubRunner`** + **`SubprocessJsonRunner`** + **`echo_kernel`**, guarded session load, CLI exit codes / **`--json`** / **`--dry-run`**; **`knowledge/fabrication-assist-layer.md`** + **`docs/FABRICATION_ASSIST.md`**; tests **`test_fabrication_assist*.py`**. Not wired to FastAPI on **`main`** unless you opt in.

---

## Request spine (one screen)

```
Client → agent/main.py
  → routers/agent.py::POST /agent
  → agent_loop.autonomous_run()
       load_config → aspect select → optional engineering execute pipeline (when enabled + mode execute)
       → _build_system_head() → decision loop (micro-decisions: tool / reason / think)
       tools → registry.TOOLS (allow_write / allow_run / approval)
  → stream or JSON result
```

Approvals: tool returns `approval_required` → **`shared_state.pending`** → **`POST /approve`**.

---

## Workflow discipline (Cursor and humans)

The repo is set up for **disciplined** changes. **You** enforce the habit:

1. **Small steps** — one logical change per pass (or one bug, one endpoint, one doc).
2. **Tight scope** — state the goal in one sentence; do not expand into unrelated refactors.
3. **Patch-style edits** — prefer minimal diffs: edit the smallest region, preserve structure, match existing patterns (**`docs/RULES.md`**, runtime **anti-drift** block).
4. **Read order** — **`PROJECT_BRAIN.md`** (this) → **`AGENTS.md`** if touching code → **`ARCHITECTURE.md`** if flow changes → **`docs/IMPLEMENTATION_STATUS.md`** if North Star mapping moves → **`docs/MODULE_SWEEP_STATUS.md`** when scoping a subsystem; then open only the relevant **`docs/*_MODULE_SECOND_SWEEP.md`** for that area.
5. **Checklist before merge** — **`docs/RELEASE_CHECKLIST.md`** for commits you intend to ship.

---

## System Deep References

This project maintains **uniform technical depth** documentation. Full coverage of tracked module clusters is in **[`docs/MODULE_SWEEP_STATUS.md`](docs/MODULE_SWEEP_STATUS.md)** (other sweeps—Install, Main, Runtime, Research, Capabilities, Layla core—also live under `docs/`; the status table is authoritative).

### Module Sweeps

Individual subsystem deep dives (examples):

- UI → [`docs/UI_MODULE_SECOND_SWEEP.md`](docs/UI_MODULE_SECOND_SWEEP.md)
- Agent Loop → [`docs/AGENT_LOOP_MODULE_SECOND_SWEEP.md`](docs/AGENT_LOOP_MODULE_SECOND_SWEEP.md)
- Services → [`docs/SERVICES_MODULE_SECOND_SWEEP.md`](docs/SERVICES_MODULE_SECOND_SWEEP.md)
- Routers → [`docs/ROUTERS_MODULE_SECOND_SWEEP.md`](docs/ROUTERS_MODULE_SECOND_SWEEP.md)
- Geometry → [`docs/GEOMETRY_MODULE_SECOND_SWEEP.md`](docs/GEOMETRY_MODULE_SECOND_SWEEP.md)
- MCP / CLI → [`docs/MCP_MODULE_SECOND_SWEEP.md`](docs/MCP_MODULE_SECOND_SWEEP.md)
- Integrations → [`docs/INTEGRATIONS_MODULE_SECOND_SWEEP.md`](docs/INTEGRATIONS_MODULE_SECOND_SWEEP.md)

### Purpose

These documents provide:

- Full internal structure of the subsystem
- Invariants and contracts
- Risk surfaces (sandbox, approval, I/O)
- Mapping to tests and verification where applicable

**Behavior:** Use **`PROJECT_BRAIN.md`** for high-level understanding first; consult **one** module sweep only when deeper detail is required for that area.

---

## AI Usage Rules

- **`PROJECT_BRAIN.md`** is the primary source of system understanding.
- Module sweeps (`docs/*_MODULE_SECOND_SWEEP.md`) are secondary deep references.
- Do **not** re-analyze the entire repository when these documents are sufficient for the task.

---

## When to update this file

- New **top-level** routes, state stores, or major directories.
- Doc roles change (e.g. a new canonical “contract” doc).
- **Not** for every new tool or tweak—those belong in **`CHANGELOG.md`** and **`AGENTS.md`** detail.

---

## Quick links

| Need | File |
|------|------|
| Add a tool | **`AGENTS.md`** → How to add a tool; **`agent/layla/tools/registry.py`** |
| Geometry / CAD programs | **`agent/layla/geometry/`**, **`docs/RUNBOOKS.md`** (Geometry programs section) |
| Add an aspect | **`personalities/<id>.json`** + **`AGENTS.md`** |
| Config keys | **`agent/runtime_config.example.json`**, **`docs/CONFIG_REFERENCE.md`** |
| Release | **`docs/RELEASE_CHECKLIST.md`** |
