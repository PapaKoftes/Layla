<!-- refreshed: 2026-06-29 -->
---
last_mapped_commit: dc0b9c0ad8bdb1cba9afea771ad54a55473ec14d
---
# Architecture

**Analysis Date:** 2026-06-29

## System Overview

Layla is a **monolithic, single-process, local-first AI agent server**. A FastAPI
application (`agent/main.py`, 930 lines) hosts every capability in one Python
process: HTTP/WebSocket routers, an autonomous agent loop, a large flat services
layer, the reusable `layla/` core package, and a static browser UI. There is
**one model and one generation lock** — all LLM completions across all routes
serialize through a single gateway. No microservices, no message broker, no
external orchestration; the process is the system boundary.

```text
┌─────────────────────────────────────────────────────────────┐
│   Browser UI  (static)            CLI / TUI / integrations    │
│   `agent/ui/` (HTML+29 JS)        `agent/tui.py`, transports/ │
└──────────────────────────┬──────────────────────────────────┘
                           │ HTTP / WebSocket / SSE
                           ▼
┌─────────────────────────────────────────────────────────────┐
│           FastAPI app  +  38 routers  (HTTP boundary)        │
│   `agent/main.py`  ·  `agent/routers/*.py`                   │
│   primary chat entry: `routers/agent.py` → stream_reason     │
└──────────────────────────┬──────────────────────────────────┘
                           │ in-process function calls
                           ▼
┌─────────────────────────────────────────────────────────────┐
│                  Agent Loop  (orchestrator)                  │
│   `agent/agent_loop.py`  (4119 lines — the spine)           │
│   autonomous_run / stream_reason: plan → infer → dispatch    │
│   → completion gate → memory writes                          │
└───────┬──────────────────────┬───────────────────┬──────────┘
        │                      │                   │
        ▼                      ▼                   ▼
┌──────────────┐   ┌────────────────────┐   ┌──────────────────┐
│ Services     │   │  LLM Gateway       │   │  Tool Dispatch   │
│ (203 modules)│   │  one global lock   │   │  + TRUST BOUNDARY│
│ `services/`  │   │ `llm_gateway.py` + │   │`tool_dispatch.py`│
│              │   │`inference_router`  │   │ sandbox/approval │
└──────┬───────┘   └─────────┬──────────┘   └────────┬─────────┘
       │                     │                       │
       ▼                     ▼                       ▼
┌─────────────────────────────────────────────────────────────┐
│   layla/ core package  ·  local GGUF model  ·  workspace     │
│   memory (SQLite+Chroma), tools, codex, geometry, scheduler  │
│   `agent/layla/**`   ·   sandbox_root (filesystem)           │
└─────────────────────────────────────────────────────────────┘
```

## Component Responsibilities

| Component | Responsibility | File |
|-----------|----------------|------|
| FastAPI app | Process lifespan, middleware, static mounts, router wiring | `agent/main.py` |
| Routers (38) | HTTP/WS/SSE surface; thin adapters to agent loop + services | `agent/routers/*.py` |
| Chat entry | `/agent` streaming endpoint → `stream_reason` | `agent/routers/agent.py` |
| Agent loop | Plan → infer → dispatch tools → gate → persist | `agent/agent_loop.py` |
| LLM gateway | Single serialized completion access point; model cache + locks | `agent/services/llm_gateway.py` |
| Inference router | Backend selection (llama.cpp / Ollama / OpenAI-compatible) | `agent/services/inference_router.py` |
| Tool dispatch | Intent → tool execution; sandbox + approval enforcement | `agent/services/tool_dispatch.py` |
| Services layer | 203 flat capability modules (planner, memory_router, etc.) | `agent/services/` |
| Core package | Reusable domain logic (memory, tools, codex, geometry, scheduler) | `agent/layla/**` |
| Config | Cached `runtime_config.json` loader; hardware-derived defaults | `agent/runtime_safety.py`, `agent/config_schema.py` |
| Shared state | Per-request conversation/steer/cancel/lease state (locked) | `agent/shared_state.py` |

## Pattern Overview

**Overall:** Monolithic layered server with a single orchestration loop and a flat
service registry.

**Key Characteristics:**
- **One model, one lock** — every completion serializes through `_llm_lock` /
  `llm_generation_lock` (`services/llm_gateway.py:69,76`); local llama.cpp KV
  cache is reset per call (`services/inference_router.py:272`).
- **Lazy / function-local imports** — heavy deps (ChromaDB, model, services) are
  imported inside functions, not at module top, so startup stays fast and
  optional features degrade gracefully (e.g. `routers/agent.py:39`, dozens of
  `from services... import` inside `agent_loop.py`).
- **Config-driven** — behavior comes from `runtime_config.json`, loaded once and
  cached with a TTL (`runtime_safety.load_config`, line 186), defaults derived
  from probed hardware.
- **Trust boundary at tool dispatch** — the LLM is untrusted; the security
  boundary is enforced where tool intents execute against the filesystem.

## Layers

**HTTP / Boundary layer:**
- Purpose: Translate transport (HTTP/WS/SSE) into in-process calls.
- Location: `agent/main.py`, `agent/routers/`
- Contains: 38 `APIRouter`s wired in `main.py:550-647`; static UI mounts.
- Depends on: agent loop, services, shared_state.
- Used by: browser UI, TUI, integrations, OpenAI-compatible clients.

**Orchestration layer:**
- Purpose: Drive one autonomous agent turn end-to-end.
- Location: `agent/agent_loop.py` (4119 lines, the single largest module),
  with outer HTTP entry via `services/coordinator.run`.
- Contains: `autonomous_run` (line 2244), `stream_reason` (line 770), planning
  gates, tool-dispatch invocation, completion gate, distillation trigger.
- Depends on: llm_gateway, tool_dispatch, services, layla core.

**Services layer:**
- Purpose: Flat catalog of 203 capability modules.
- Location: `agent/services/`
- Contains: `planner.py`, `model_router.py`, `memory_router.py`,
  `system_head_builder.py`, `debate_engine.py`, `tool_policy.py`, etc.
- Note: flat namespace, no sub-package hierarchy except `services/sandbox/`.

**Core package (`layla/`):**
- Purpose: Reusable, transport-agnostic domain logic.
- Location: `agent/layla/`
- Contains: `memory/` (SQLite + Chroma + graph), `tools/` (registry + impl +
  domains), `codex/`, `geometry/` + `cam/`, `scheduler/`, `ingestion/`,
  `skills/`.

## Data Flow

### Primary Request Path (chat turn)

1. Browser/UI POSTs to `/agent` → `routers/agent.py` streaming handler.
2. Trivial turns short-circuit via `_quick_reply_for_trivial_turn`
   (`agent_loop.py:837` gating, avoids ChromaDB/graph/workspace).
3. `coordinator.run(autonomous_run, ...)` wraps resume/worktree/consolidation
   (`routers/agent.py:42`); the flight takes a serialize lock
   (`get_agent_serialize_lock`, `llm_gateway.py:82`).
4. `autonomous_run` (`agent_loop.py:2244`) builds the system head, plans, then
   loops: completion via `run_completion` → `inference_router` behind the global
   model lock (`inference_router.py:320`).
5. Tool intents dispatched through `services/tool_dispatch.dispatch_tool_intent`
   (`agent_loop.py:3557`); sandbox + approval enforced (`tool_dispatch.py:177-196`).
6. **Strict completion gate** retries low-quality output instead of returning it
   (`agent_loop.py:3842`).
7. On outcome, memory is distilled/persisted (`run_distill_after_outcome`,
   `agent_loop.py:4041`); response streamed back as SSE.

### Inference Backend Selection

1. `effective_inference_backend(cfg)` picks llama.cpp / Ollama / OpenAI-compatible
   (`inference_router.py:62`).
2. Model resolved + cached per path in `_llm_by_path`, bounded to
   `max_resident_models` with LRU-style eviction (`inference_router.py:35`).

**State Management:**
- Per-request conversation, steer, cancel, and workspace-lease state held in
  `agent/shared_state.py`, each guarded by its own `threading.Lock`.
- Durable state in SQLite (`layla/memory/db.py`) + optional Chroma vectors.

## Key Abstractions

**Tool registry:**
- Purpose: Map tool names → implementations, assembled from domain modules.
- Examples: `layla/tools/registry.py` (merges `FILE_TOOLS`, `WEB_TOOLS`,
  `GEOMETRY_TOOLS`, ... at line 22), `layla/tools/domains/*`, `layla/tools/impl/*`.

**LLM completion gateway:**
- Purpose: Single serialized entry to the model regardless of backend.
- Examples: `services/llm_gateway.py`, `services/inference_router.py`.

**System head:**
- Purpose: Assemble the prompt/context for each turn.
- Examples: `services/system_head_builder.py` (1086 lines).

## Entry Points

**HTTP server:**
- Location: `agent/main.py` (`app = FastAPI(...)`, line 385), launched via
  `agent/serve.py` / `agent/launcher.py` / `layla.py`.
- Triggers: browser UI, integrations, OpenAI-compatible clients.

**TUI:**
- Location: `agent/tui.py` — terminal front end over the same loop.

**Background worker:**
- Location: `agent/background_job_worker.py`, `services/agent_task_runner.py`.

## Architectural Constraints

- **Threading / single model:** One process, one resident default model; all
  generation serialized by `llm_generation_lock` (`llm_gateway.py:76`). Local
  llama.cpp KV cache is fully reset each call to avoid cross-turn contamination
  (`inference_router.py:272-277`).
- **Model cache bound:** `_llm_by_path` capped (`_DEFAULT_MAX_RESIDENT_MODELS=2`,
  `inference_router.py:22`) to prevent OOM — this was a fixed SPOF (commit dc0b9c0).
- **Global state:** Module-level singletons in `llm_gateway.py` (`_llm`,
  `_llm_by_path`, lock objects) and many per-concern locks in `shared_state.py`.
- **Lazy imports as policy:** Top-of-function imports are intentional; do not hoist
  heavy imports to module top (breaks fast startup + graceful degradation).
- **Python runtime gate:** Startup hard-checks the interpreter
  (`setup/python_compat.py`, enforced in `main.py:21-50`); 3.11–3.12 preferred,
  Chroma auto-disabled on unofficial runtimes.

## Anti-Patterns

### God module (`agent_loop.py`)

**What happens:** The 4119-line agent loop concentrates planning, inference,
tool dispatch, gating, and persistence.
**Why it's wrong:** Hard to test in isolation; high merge-conflict surface.
**Do this instead:** Extend by adding to the relevant `services/` module and
calling it from the loop (the codebase already extracts tool dispatch into
`services/tool_dispatch.py`); avoid growing `agent_loop.py`.

### Hoisting heavy imports to module top

**What happens:** Importing ChromaDB / model / large services at module scope.
**Why it's wrong:** Slows startup and removes graceful degradation on minimal
runtimes (Chroma may be disabled — `main.py:35`).
**Do this instead:** Import inside the function, as existing code does
(`routers/agent.py:39`, `agent_loop.py:790`).

## Error Handling

**Strategy:** Defensive try/except with best-effort degradation around optional
subsystems (crash handler, observability, Chroma, distillation).

**Patterns:**
- Broad `except Exception` + `logger.debug(...)` for non-critical paths
  (e.g. `main.py:91-98`, `agent_loop.py:4044`).
- KV-cache corruption auto-invalidates and retries once
  (`inference_router.py:308-346`).
- Crash handler installed at startup (`services/crash_handler.py`).

## Cross-Cutting Concerns

**Logging:** Single `logging.getLogger("layla")`; optional JSON formatter via
`LAYLA_LOG_JSON`; `TaskContextFilter` injects task context (`main.py:105`).
**Validation:** Pydantic request schemas in `agent/schemas/requests.py`.
**Authentication:** None for localhost (anonymous, no PII logged, `main.py:74`);
optional bearer token for non-localhost when `remote_enabled` (`config_schema.py:262`).
**Security boundary:** Sandbox-root + approval enforced in
`services/tool_dispatch.py`; LLM output is treated as untrusted input.

---

*Architecture analysis: 2026-06-29*
