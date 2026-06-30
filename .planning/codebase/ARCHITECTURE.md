<!-- refreshed: 2026-06-30 -->
# Architecture

**Analysis Date:** 2026-06-30

## System Overview

Layla is a local-first AI companion/agent platform (v1.4.0 "Castilla"): a FastAPI
backend driving local llama.cpp inference, an autonomous agent loop, a deep
service layer, and an ES-module browser UI. Everything runs on the operator's
own machine; cloud providers are optional.

```text
┌─────────────────────────────────────────────────────────────────────────┐
│                       Browser UI  (ES modules)                            │
│   `agent/ui/main.js` → core/{bus,state,actions,overlay} + components/*    │
│   Active aspect (personality) re-themes the shell via CSS vars + SVG      │
└───────────────────────────────┬───────────────────────────────────────────┘
                                 │  HTTP / WebSocket  (/layla-ui, /ws)
                                 ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                    FastAPI app  `agent/main.py`                            │
│   ~40 routers in `agent/routers/*` (agent, plans, memory, aspects, …)     │
│   lifespan() spins up background threads, hardware probe, governor         │
└───────────────────────────────┬───────────────────────────────────────────┘
                                 │
                                 ▼
┌─────────────────────────────────────────────────────────────────────────┐
│              Agent loop  `agent/agent_loop.py` (910 lines)                 │
│   orchestrates → `agent/services/agent/*` (decision_loop, stream_handler, │
│   reasoning_handler, tool_guards, verification_engine, run_finalizer …)   │
│   Aspect selection: `agent/orchestrator.py`                               │
└───────────────────────────────┬───────────────────────────────────────────┘
                                 │
                                 ▼
┌─────────────────────────────────────────────────────────────────────────┐
│         Service layer  `agent/services/` — 19 sub-packages                 │
│  llm · memory · context · planning · reasoning · retrieval · tools ·       │
│  skills · safety · governance · sandbox · cluster · personality ·         │
│  prompts · observability · infrastructure · user · workspace · agent      │
│  (legacy flat `services/*.py` are backward-compat shims → sub-packages)    │
└───────┬─────────────────────────────┬─────────────────────────┬───────────┘
        ▼                             ▼                         ▼
┌───────────────┐          ┌─────────────────────┐    ┌──────────────────────┐
│ llama.cpp /    │          │ SQLite `layla.db` +  │    │ ResourceGovernor      │
│ local models   │◄─────────│ Chroma vectors /     │    │ WHISPER/BREATHE/SPRINT │
│ (LLM gateway)  │ governs  │ search bridges       │    │ throttles inference    │
└───────────────┘ threads   └─────────────────────┘    └──────────────────────┘
```

## Component Responsibilities

| Component | Responsibility | File |
|-----------|----------------|------|
| Server entrypoint | Port-guarded launch, browser open | `agent/serve.py` |
| FastAPI app | Routers, lifespan, static mounts, runtime gate | `agent/main.py` |
| Agent loop | Top-level autonomous run orchestration | `agent/agent_loop.py` |
| Decision loop | decision→intent→tool/reason iteration | `agent/services/agent/decision_loop.py` |
| Aspect orchestrator | Selects which personality responds | `agent/orchestrator.py` |
| LLM gateway | Local inference, model load/unload, governor-aware threads | `agent/services/llm/llm_gateway.py` |
| Resource governor | OS-input-driven compute throttle | `agent/services/infrastructure/resource_governor.py` |
| Install/provision | First-run, hardware probe, model download | `agent/install/` |
| UI shell | ES-module bus/state/actions, components | `agent/ui/main.js` |

## Pattern Overview

**Overall:** Layered modular monolith with an event-driven agent core.

**Key Characteristics:**
- Local-first: inference, storage, search all run on-device by default.
- 19 cohesive service sub-packages under `agent/services/`, fronted by
  backward-compat shim modules so old import paths keep working.
- Decomposed agent loop: a thin top-level loop delegating to single-purpose
  handler modules in `services/agent/`.
- Reactive UI: a single ES-module entry with an event bus + centralized state.
- Dynamic resource adaptation via the `ResourceGovernor`.

## The Backward-Compat Shim Pattern (CRITICAL)

The refactor moved ~204 flat `agent/services/*.py` files into 19 sub-packages.
The **207 flat files that remain at `agent/services/` are now shims**, not real
logic. Each shim re-exports the relocated module:

```python
# agent/services/llm_gateway.py
"""Backward compatibility -- module moved to services/llm/llm_gateway.py"""
import importlib as _importlib
import sys as _sys

_real = _importlib.import_module("services.llm.llm_gateway")
_sys.modules[__name__] = _real
```

The `sys.modules[__name__] = _real` line aliases the whole module object, so
`import services.llm_gateway` and `import services.llm.llm_gateway` return the
*same* object. **Real logic lives in the sub-package** (e.g.
`services/llm/llm_gateway.py`); never edit the shim. ADR-003 documents this.

**Where real logic lives (sub-package → domain):**

| Sub-package | Domain | Examples |
|-------------|--------|----------|
| `services/agent/` | Decomposed loop phases | `decision_loop.py`, `stream_handler.py`, `reasoning_handler.py`, `verification_engine.py`, `run_finalizer.py` |
| `services/llm/` | Inference + models | `llm_gateway.py`, `model_manager.py`, `inference_router.py`, `litellm_gateway.py` |
| `services/memory/` | Long-term/semantic memory, KG | `personal_knowledge_graph.py`, `memory_consolidation.py`, `working_memory.py` |
| `services/context/` | Context assembly + budgeting | `context_builder.py`, `context_budget.py`, `context_merge_layers.py` |
| `services/planning/` | Plans, multi-agent, tasks | `planner.py`, `plan_executor.py`, `multi_agent.py`, `task_graph.py` |
| `services/reasoning/` | Research reasoning stages | `research_intelligence.py`, `research_stages.py` |
| `services/retrieval/` | Search + caches | `search_router.py`, `keyword_search.py`, `elasticsearch_bridge.py`, `reranker.py` |
| `services/tools/` | Tool dispatch + policy | `tool_dispatch.py`, `tool_policy.py`, `intent_router.py` |
| `services/skills/` | Skill packs + sandbox | `skill_registry.py`, `skill_sandbox.py`, `plugin_loader.py` |
| `services/safety/` | Guards, secrets, auth | `secret_filter.py`, `url_guard.py`, `content_guard.py`, `auth.py`, `decision_policy.py` |
| `services/governance/` | Tunnel auth/audit | `tunnel_auth.py`, `tunnel_audit.py` |
| `services/sandbox/` | Code execution | `python_runner.py`, `shell_runner.py`, `sandbox_validator.py` |
| `services/cluster/` | Distributed compute | `cluster_network.py`, `drone_worker.py`, `mdns_discovery.py` |
| `services/personality/` | Aspects/character | `aspect_behavior.py`, `character_creator.py`, `maturity_engine.py` |
| `services/prompts/` | Prompt construction | `prompt_builder.py`, `system_head_builder.py` |
| `services/observability/` | Logs/metrics/traces | `metrics.py`, `prom_metrics.py`, `tracing.py`, `security_audit.py` |
| `services/infrastructure/` | Runtime, hardware, governor | `resource_governor.py`, `hardware_detect.py`, `worker_pool.py` |
| `services/user/` | Onboarding | `onboarding_interview.py` |
| `services/workspace/` | Code/repo/file intelligence | `repo_indexer.py`, `code_intelligence.py`, `doc_ingestion.py` |

## Layers

**UI layer:**
- Location: `agent/ui/`
- ES modules: `core/` (bus, state, actions, overlay, compat), `services/`
  (api, health, utils), `components/*` (~28 view modules).
- `main.js` is the single `<script type="module">` entry; a compat bridge
  exposes module APIs onto `window.*` during the IIFE→ESM migration.

**API layer:**
- Location: `agent/routers/`, registered in `agent/main.py` via `include_router`.
- ~40 routers grouped by domain (agent, plans, memory, aspects, research, …).

**Agent core:**
- Location: `agent/agent_loop.py` + `agent/services/agent/`.
- Loop decomposed 1574→910 lines; phases live in `services/agent/*`.

**Service layer:**
- Location: `agent/services/<sub-package>/`.
- 19 sub-packages; flat shims preserve legacy import paths.

**Inference/storage:**
- llama.cpp via `services/llm/`; SQLite `layla.db`; Chroma vectors; optional
  Elasticsearch/Meilisearch bridges in `services/retrieval/`.

## Data Flow

### Primary Request Path (chat/agent run)

1. UI sends request via `agent/ui/services/api.js` to a router (`agent/routers/agent.py`).
2. Router invokes the agent loop (`agent/agent_loop.py`).
3. Aspect orchestrator picks the responding personality (`agent/orchestrator.py`).
4. Decision loop iterates (`agent/services/agent/decision_loop.py`): intent →
   tool dispatch (`services/tools/tool_dispatch.py`) or reasoning
   (`services/agent/reasoning_handler.py`).
5. LLM gateway runs inference, thread count gated by the governor
   (`services/llm/llm_gateway.py`).
6. Stream + UX events flow back over WebSocket; run is finalized and memory
   written (`services/agent/run_finalizer.py`).

### Resource governance flow

1. Governor samples OS input idle time (`resource_governor.py`, Windows
   `GetLastInputInfo` via ctypes; CPU heuristics elsewhere).
2. Mode resolves: WHISPER (user active) / BREATHE (1–10m idle) / SPRINT (10m+).
3. `llm_gateway.py:486-494` calls `get_governor().get_inference_threads()` so
   active-user inference uses fewer threads; WHISPER schedules idle model unload.

### UI aspect re-theming

1. Active aspect selected; `agent/ui/components/aspect.js` holds the per-aspect
   color palette and sets CSS vars (`--asp`, `--asp-glow`, `--asp-mid`).
2. Per-aspect SVGs load from `agent/ui/assets/sigils/` and `agent/ui/aspects/*.svg`.

**State Management:**
- Backend: per-run session context (ADR-002 replaced global `shared_state`);
  see `services/infrastructure/session_context.py`.
- Frontend: centralized `appState` + event `bus` in `agent/ui/core/`.

## Key Abstractions

**Aspect (personality):**
- Purpose: a selectable persona that responds and re-themes the UI.
- Examples: `agent/orchestrator.py`, `services/personality/aspect_behavior.py`, `personalities/`.

**ResourceGovernor:**
- Purpose: adapt compute to user presence.
- Pattern: singleton via `get_governor(cfg)`; modes `ResourceMode.{WHISPER,BREATHE,SPRINT}`.

**Service shim:**
- Purpose: keep legacy `services.X` imports working post-refactor.
- Pattern: `sys.modules[__name__] = _real`.

## Entry Points

**`agent/serve.py`** — run from `agent/`; port-guarded server launch.
**`agent/main.py`** — FastAPI `app`; runtime Python gate, routers, lifespan.
**`agent/install/`** — provisioning: hardware probe → kit/model recommender → download → first run.

## Architectural Constraints

- **Runtime gate:** `agent/main.py` enforces Python 3.11/3.12 (3.13+ best-effort);
  Chroma auto-disables on incompatible interpreters (`setup/python_compat.py`).
  Note: local dev here cannot run Layla (3.14 vs required 3.12) — verify statically.
- **Threading:** FastAPI + many tracked background threads spawned in `lifespan`;
  inference thread count is governor-controlled.
- **Global state:** module-level singletons exist (governor, aspect cache in
  `orchestrator.py`); ADR-002 moved request state off global `shared_state`.
- **Compiler-free fallback:** memory stack degrades gracefully when native
  build tools / Chroma are unavailable.

## Anti-Patterns

### Editing a flat shim module
**What happens:** Adding logic to `agent/services/foo.py`.
**Why it's wrong:** It is a shim; `sys.modules` aliasing makes edits dead or confusing.
**Do this instead:** Edit the real module in the sub-package, e.g. `agent/services/<pkg>/foo.py`.

### Reaching into global request state
**What happens:** Using module-global mutable state for per-run data.
**Why it's wrong:** ADR-002 replaced this; it breaks concurrent runs.
**Do this instead:** Thread state through session context (`services/infrastructure/session_context.py`).

### Growing the top-level agent loop
**What happens:** Adding phases inline in `agent/agent_loop.py`.
**Why it's wrong:** Undoes the 1574→910 decomposition (ADR-001).
**Do this instead:** Add a focused handler module under `agent/services/agent/`.

## Error Handling

**Strategy:** Defensive degradation — optional subsystems wrapped in try/except
with debug logging; the platform stays up when extras fail.

**Patterns:**
- Recovery services: `services/infrastructure/{failure_recovery,crash_handler,dependency_recovery}.py`.
- Verification gate before finalize: `services/agent/verification_engine.py`.

## Cross-Cutting Concerns

**Logging/metrics/traces:** `agent/services/observability/` (`structured_log.py`, `prom_metrics.py`, `tracing.py`).
**Validation:** `agent/core/validator.py`, `services/tools/tool_output_validator.py`.
**Safety/auth:** `agent/services/safety/` (`auth.py`, `secret_filter.py`, `url_guard.py`).
**Governance:** tunnel auth/audit in `agent/services/governance/`.

## Design References

ADRs: `agent/docs/adr/001-agent-loop-decomposition.md` … `006-companion-first-product-rules.md`.
Vision: `agent/docs/VISION.md` (companion-first 10-phase plan). Design set: `docs/design/00-13`.

---

*Architecture analysis: 2026-06-30*
