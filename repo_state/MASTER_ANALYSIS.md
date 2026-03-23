# MASTER_ANALYSIS.md — Layla Repository Canonical Analysis

> Generated: 2026-03-23 | Branch: claude/xenodochial-feistel | Version: 1.0.0 (Beta)
> Read AGENTS.md, PROJECT_BRAIN.md, ARCHITECTURE.md, docs/GOLDEN_FLOW.md, docs/IMPLEMENTATION_STATUS.md, LAYLA_NORTH_STAR.md before modifying this repo.

---

## 1. System Overview

### Purpose
Layla is a **self-hosted, local-first AI companion and engineering agent** built on GGUF models via llama-cpp-python. No cloud, no API keys required. Primary operator context is CAD/fabrication/programming work (NcHops, PolyBoard, OptiNest domain). The system runs as a FastAPI server at `localhost:8000`, exposing a chat UI, CLI, MCP (for Cursor), Discord/Slack/Telegram transports, and an HTTP API that all surfaces converge on identically.

### Current Maturity
**Beta (v1.0.0)**. The implementation status (docs/IMPLEMENTATION_STATUS.md) shows all 20 North Star sections are implemented. The codebase is production-hardened with: TTL-cached config, WAL SQLite, multi-backend retrieval, approval gates, tool-loop detection, sandbox isolation, and CI (Python 3.11+3.12 matrix, ruff lint, Playwright e2e). Missing: RL feedback loop, OpenTelemetry, DAG skill composition, full streaming STT, model A/B comparison.

### Core Design Philosophy
- **Local-first, privacy-first**: No telemetry leaves the machine. SQLite and ChromaDB are local. Uncensored by default (`uncensored: true`, `nsfw_allowed: true`).
- **Operator-sovereign**: The operator installs their GGUF, controls config, approves all destructive actions. Layla cannot modify herself without approval.
- **One consciousness, six aspects**: Morrigan/Nyx/Echo/Eris/Lilith/Cassandra are routing lenses on one model; orchestrator selects via keyword/embedding match, not hard switches.
- **Bounded, non-autonomous**: Tool calls capped (`max_tool_calls`, `max_runtime_seconds`). No background autonomous runs that write files or execute code without user approval. Study scheduler is read-only.
- **Learn → Plan → Assist → Evaluate → Improve** execution loop (LAYLA_NORTH_STAR §6).

---

## 2. Architecture Breakdown

### Top-Level Structure
```
/ (repo root)
├── agent/              # All Python runtime (FastAPI server)
├── fabrication_assist/ # Standalone adapter layer (NOT imported by agent/main.py by default)
├── cursor-layla-mcp/   # MCP stdio bridge for Cursor IDE
├── discord_bot/        # Full Discord bot (voice, TTS, music)
├── transports/         # Slack (Socket Mode) + Telegram polling
├── personalities/      # 6 aspect JSON files (glob-loaded dynamically)
├── knowledge/          # Gitignored. Operator .md/.txt for RAG indexing.
├── models/             # Gitignored. GGUF files go here.
├── plugins/            # Plugin manifests (plugin.yaml)
├── skills/             # Optional SKILL.md files
├── layla.py            # CLI entry (httpx to localhost:8000)
├── layla.db            # SQLite (repo root, gitignored)
└── docs/               # All design docs
```

### Core Modules (agent/)
| Layer | Module | Role |
|-------|--------|------|
| **Entry** | `main.py` | FastAPI app + lifespan (scheduler, plugin load, DB migrate, prewarm). All routes. |
| **Decision kernel** | `agent_loop.py` | `autonomous_run()`: reasoning classify → aspect select → context build → decision loop → output |
| **Aspect selection** | `orchestrator.py` | Keyword scoring + embedding cosine for personality dispatch; deliberation prompt builder |
| **Safety** | `runtime_safety.py` | TTL-cached config, hardware probe, sandbox check, file-level cache, protected file list |
| **State** | `shared_state.py` | Shared refs between main.py and routers (history deque, pending approvals, touch_activity) |
| **Decision parsing** | `decision_schema.py` | Pydantic `AgentDecision`, `parse_decision()` → structured tool/reason/none |
| **Tool registry** | `layla/tools/registry.py` | All ~109 tools + `TOOLS` dict; sandbox enforcement; write/run gates |
| **Memory (SQL)** | `layla/memory/db.py` | SQLite + WAL; all tables + FTS5; incremental migrations |
| **Memory (vector)** | `layla/memory/vector_store.py` | ChromaDB + nomic-embed-text-v1.5 (768d, MiniLM fallback); BM25+vector+rerank pipeline |
| **Memory (distill)** | `layla/memory/distill.py` | Quality gate + Jaccard/semantic similarity dedup |
| **Retrieval** | `services/retrieval.py` | Unified: vector*0.5 + BM25*0.3 + graph*0.2 + confidence*0.1; parallel fetch |
| **LLM gateway** | `services/llm_gateway.py` | `run_completion()` + `RLock` serialization; multi-GGUF routing via ContextVar |
| **Context assembly** | `services/context_manager.py` | Token-budgeted prompt assembly; conversation summarization at 75% of n_ctx |
| **Planner** | `services/planner.py` | `create_plan()` → LLM-generated 3-6 step plans with tool hints |
| **Task graph** | `services/task_graph.py` | `TaskNode`/`TaskGraph`/`GraphExecutor`; parallel execution by dependency order |
| **Mission manager** | `services/mission_manager.py` | Long-running goals: plan → persist → APScheduler worker executes steps |
| **Reasoning classifier** | `services/reasoning_classifier.py` | `none`|`light`|`deep` heuristic; gates planner + self-reflection |
| **Cognitive workspace** | `services/cognitive_workspace.py` | Tree-of-thought: 3 approaches → evaluate → choose best; injects `strategy_hint` |
| **Model router** | `services/model_router.py` | Route by task type (coding/reasoning/chat) to per-task GGUF |
| **System optimizer** | `services/system_optimizer.py` | Runtime adaptive config; CPU/RAM/GPU pressure overrides; never persists |
| **Graph reasoning** | `services/graph_reasoning.py` | spaCy NER + networkx graph expansion for query context |
| **Geometry** | `layla/geometry/` | `GeometryProgram` schema + `execute_program()` + backends (ezdxf/cadquery/openscad/trimesh) + HTTP bridge |
| **File understanding** | `layla/file_understanding.py` | `analyze_file()` for all North Star extensions (CAD, G-code, Python, etc.) |
| **Config schema** | `config_schema.py` | `EDITABLE_SCHEMA` — single source of truth for /settings UI and API |
| **Output polish** | `services/output_polish.py` | Final reply cleanup before sending |

### Routers
| Router | Endpoints |
|--------|-----------|
| `routers/agent.py` | `POST /agent`, `POST /learn/`, `GET /memories` |
| `routers/approvals.py` | `POST /approve`, `GET /pending` |
| `routers/study.py` | `GET /wakeup`, `/study_plans`, `/study_plans/presets`, `/suggestions` |
| `routers/research.py` | `/research_mission`, `/missions`, `/mission/{id}` |
| `main.py` (inline) | `/health`, `/health/deps`, `/settings`, `/platform/*`, `/voice/*`, `/ui`, `/v1/*`, etc. |

### Data Flow — Request Lifecycle
```
POST /agent {message, workspace_root, allow_write, allow_run, aspect_id, stream}
  → routers/agent.py
    → [fast paths: empty msg, trivial greeting, response cache hit]
    → agent_loop.autonomous_run()
      1. runtime_safety.load_config()  [TTL=2s, mtime-checked]
      2. system_optimizer.get_effective_config()  [runtime overrides, never persists]
      3. reasoning_classifier.classify_reasoning_need()  → none|light|deep
      4. model_router.classify_task_for_routing()  → set ContextVar for llm_gateway
      5. orchestrator.select_aspect()  [keyword score → embedding cosine if score=0]
      6. _build_system_head()
         → identity (system_identity.txt) + aspect systemPromptAddition
         → knowledge RAG (vector+BM25+FTS5+graph → rerank → top 5)
         → learnings (SQLite, score-filtered)
         → companion context (relationship_memory, timeline, user_identity, goals)
         → optional: cognitive_lens, behavioral_rhythm, style_profile, lens_knowledge
      7. cognitive_workspace (if enable_cognitive_workspace)  [tree-of-thought]
      8. planner.create_plan() / execute_plan()  [if should_plan]
      9. DECISION LOOP (up to max_tool_calls, max_runtime_seconds):
         → _llm_decision() → parse JSON {action, tool, args, objective_complete}
         → action=tool: registry.TOOLS[name](**args)
           [gated: allow_write/allow_run + approval flow if needed]
         → action=reason/objective_complete: _completion() → stream final reply
        10. Optional self-reflection: score + rewrite if < 7/10
        11. _save_outcome_memory() → distill → learnings + reflection engine
        12. telemetry.log_event() → telemetry_events SQLite
    → Response JSON {response, state, reasoning_mode, conversation_id}
```

### Entry Points
- `uvicorn agent.main:app --host 127.0.0.1 --port 8000` (production)
- `layla.py ask "..."` (CLI → httpx to :8000)
- `cursor-layla-mcp/server.py` (MCP stdio → :8000)
- `discord_bot/run.py` (Discord bot → :8000)
- `transports/slack_bot.py`, `transports/telegram_bot.py` (same /agent bridge)
- `fabrication_assist/assist/__main__.py` (standalone; NOT connected to main agent loop by default)

---

## 3. Source of Truth Mapping

| Concern | Authoritative Source | Notes |
|---------|---------------------|-------|
| Vision / features | `LAYLA_NORTH_STAR.md` | NEVER modify unless operator asks explicitly |
| Implementation status | `docs/IMPLEMENTATION_STATUS.md` | Maps each §§ to code + tests |
| Request lifecycle | `docs/GOLDEN_FLOW.md` | Approval semantics, cross-surface contracts |
| Operational guarantees | `docs/PRODUCTION_CONTRACT.md` | Caps, safety, /health shape, logging |
| Repository rules | `docs/RULES.md` + `AGENTS.md` | For AI and human contributors |
| Config keys + defaults | `agent/runtime_safety.py` (`defaults` dict in `load_config()`) | `runtime_config.example.json` is annotated template |
| Editable settings schema | `agent/config_schema.py` (`EDITABLE_SCHEMA`) | Drives /settings API + Web UI |
| Tool definitions | `agent/layla/tools/registry.py` (`TOOLS` dict) | 109 tools; `dangerous`, `require_approval`, `risk_level` |
| DB schema | `agent/layla/memory/db.py` (`_migrate_impl()`) | Additive only; triggers on learnings FTS5 |
| Aspect definitions | `personalities/*.json` | Always glob-loaded; never hardcode list |
| Architecture flow | `ARCHITECTURE.md` | One-page; keep updated on route/state changes |
| Ethical constraints | `docs/ETHICAL_AI_PRINCIPLES.md` | Non-clinical psychology boundary; §11 critical |
| Version | `agent/version.py` | `__version__ = "1.0.0"` |

Behavior is defined by: `agent_loop.py` > `runtime_safety.py` > `layla/tools/registry.py` > `orchestrator.py`. Documentation describes but does not override.

---

## 4. Current State vs Intended State

### Fully Implemented (per docs/IMPLEMENTATION_STATUS.md)
- All 20 NORTH_STAR sections: project context, file understanding, approval flow, geometry stack, study scheduler, wakeup initiative, remote mode, project discovery, fabrication assist boundary.
- Companion intelligence: relationship memory, timeline events, user identity, episodes, goal engine, reflection engine, curiosity engine, experience replay, personal knowledge graph, style profile.
- Intelligence systems: knowledge distiller, tool outcome learning, workspace semantic graph (tree-sitter), multi-strategy reasoning, cognitive workspace (tree-of-thought).
- Platform UI: Health/Models/Knowledge/Plugins/Projects/Study/Memory/Research/Help panels.
- Geometry: ezdxf, cadquery, openscad, trimesh backends + HTTP CAD bridge.
- Voice: faster-whisper STT + kokoro-onnx TTS with pyttsx3 fallback.
- Capability evolution pipeline: discover → sandbox → benchmark → promote.
- Discord full bot (voice, TTS, music), Slack, Telegram transports.
- OpenClaw-style core emulation: tool policy, tool loop detection, tool output validator, shell sessions, markdown skills.
- Non-clinical psychology integration: Echo/Lilith pinned framework excerpt, RAG-widened reflective triggers, OPERATOR_PSYCHOLOGY_SOURCES catalog.

### Known Gaps / Planned
| Gap | Status | Notes |
|-----|--------|-------|
| RL feedback loop | Not implemented | `IMPLEMENTATION_STATUS.md` lists as missing |
| OpenTelemetry | Not implemented | Local telemetry only (SQLite `telemetry_events`) |
| DAG skill composition + skill metrics | Not implemented | Basic skills work; no DAG wiring |
| Model A/B comparison | Not implemented | Listed as missing in model management domain |
| faiss-cpu / qdrant alternatives | Not implemented | ChromaDB + BM25 only |
| Streaming STT | Partial | `transcribe_streaming` exists; wire-up TUI incomplete |
| Matrix / WhatsApp transports | Not implemented | Noted as optional |
| `fabrication_assist` core integration | Intentional boundary | Must NOT be imported by main.py unless explicitly wired |

### Doc/Code Drift Detected
1. **`task_graph.py` location**: `ARCHITECTURE.md` references `services/task_graph.py`, but the actual file is at `agent/services/task_graph.py` (correct) — and there is no root-level `agent/task_graph.py` (the task_graph.py path in the system prompt was wrong; file lives at `agent/services/task_graph.py`).
2. **`planner.py` location**: System prompt listed `agent/planner.py` but actual file is `agent/services/planner.py`. The `services/` subdirectory is the canonical home.
3. **`completion_max_tokens` default mismatch**: `runtime_safety.py` defaults to `256`, but `config_schema.py` shows `"default": 256` in schema — these align; however the schema `"max": 8192` suggests UI exposes a wider range than typical default config.
4. **`max_tool_calls` default**: `runtime_safety.py` defaults to `2`, but `config_schema.py` schema shows `"default": 5`. The runtime_safety default is more conservative; schema for UI is aspirational. The `PRODUCTION_CONTRACT.md` states "tightened (e.g. 2)".
5. **`safe_mode` uncensored tension**: `safe_mode: True` and `uncensored: True` coexist — safe_mode gates write/run approval; uncensored controls model behavior. Not a conflict but could confuse operators expecting "uncensored = no restrictions."

---

## 5. Critical Systems

### Core Decision Loop (`agent_loop.autonomous_run`)
**Highest-impact function in the repo.** Any bug here affects every turn. Key sub-functions:
- `_build_system_head()`: assembles the full system prompt with all context layers
- `_llm_decision()`: single-turn LLM call → JSON parse → action routing
- `_write_pending()`: approval gate when write/run blocked
- `_save_outcome_memory()`: post-turn distillation + reflection

### Approval Gate (`runtime_safety` + `layla/tools/registry.py` + `routers/approvals.py`)
The single mechanism preventing autonomous destructive action. Three-part invariant:
1. `DANGEROUS_TOOLS` list in `runtime_safety.py` defines what needs approval
2. `allow_write` / `allow_run` flags from client request control per-call bypass
3. `POST /approve` executes the tool directly and logs audit — does NOT re-enter agent loop

### Memory Stack
- **SQLite** (`layla.db`): source of truth for learnings, study plans, audit, aspect memories, project context, missions, capability events, telemetry, companion context tables (15+ tables)
- **ChromaDB** (`agent/chroma/`): semantic vector index for learnings + knowledge docs; optional (degrades to FTS5)
- **FTS5** (virtual table in SQLite): Porter-stemmed keyword search; auto-sync via triggers; fallback when Chroma fails
- **BM25** (in-memory): rebuilt from learnings on count change; pure Python, no deps

### Config System (`runtime_safety.load_config`)
- TTL=2s skip on stat(); mtime-checked on change; thread-safe with `RLock`; hardware-derived defaults merged at load
- `system_optimizer.get_effective_config()` applies runtime pressure overrides; NEVER writes to disk
- Single source of truth for all runtime behavior — every service imports from here

### Geometry Subsystem (`layla/geometry/`)
- `GeometryProgram` (Pydantic-discriminated ops): dxf_begin, dxf_line, dxf_circle, dxf_lwpolyline, dxf_save, cq_box, openscad_render, mesh_info, cad_bridge_fetch
- `execute_program()`: sandbox-validates workspace_root against sandbox_root; dispatches ops to backends; supports recursive HTTP CAD bridge (depth-limited to 3)
- Bridge security: URL must match `geometry_external_bridge_url` config; `insecure_localhost` requires explicit flag

### High-Impact Files
| File | Impact | Reason |
|------|--------|--------|
| `agent/agent_loop.py` | CRITICAL | Every chat turn; ~1500+ lines; decision loop + streaming |
| `agent/runtime_safety.py` | CRITICAL | Config gate + sandbox + file protection |
| `agent/layla/tools/registry.py` | CRITICAL | All 109 tools; write/execute gates |
| `agent/layla/memory/db.py` | HIGH | SQLite schema; all memory persistence |
| `agent/main.py` | HIGH | Server entry; lifespan; scheduler; all routes |
| `agent/orchestrator.py` | HIGH | Aspect selection; deliberation; personality dispatch |
| `agent/layla/memory/vector_store.py` | HIGH | ChromaDB + embedding model load + retrieval pipeline |
| `agent/services/llm_gateway.py` | HIGH | All LLM calls; RLock serialization; multi-GGUF |

---

## 6. Invariants (MUST NEVER BREAK)

### Safety Gates
1. **Approval gate is inviolable**: `write_file`, `apply_patch`, `shell`, `run_python`, `git_commit`, `git_push`, and all `DANGEROUS_TOOLS` must return `approval_required` when `allow_write`/`allow_run` are False and no prior approval exists. Never bypass this.
2. **Sandbox containment**: All file reads/writes validated via `inside_sandbox(path)` using `Path.relative_to()` (not string prefix). Out-of-sandbox returns `{"ok": False, "error": "Outside sandbox"}`.
3. **Protected files cannot be written**: `PROTECTED_FILES = [main.py, agent_loop.py, runtime_safety.py]` — `is_protected()` blocks writes to these.
4. **Shell blocklist is hard**: `_SHELL_BLOCKLIST = [rm, del, rmdir, format, mkfs, dd, shutdown, reboot, powershell, cmd, reg, netsh, sc, taskkill, cipher]` — never removable via config.

### Memory / Schema
5. **DB schema is additive only**: All column adds go through `migrate()` via `ALTER TABLE ... ADD COLUMN`; never drop columns; migration runs at most once per process (idempotent guard).
6. **Learnings quality gate**: When `learning_quality_gate_enabled=true`, `passes_learning_quality_gate()` must be called before `db.save_learning()`; score < `learning_quality_min_score` is rejected.
7. **FTS5 sync via triggers**: `learnings_fts` is kept in sync by SQL triggers. Direct inserts to `learnings` without trigger path will break FTS.

### Personality / Identity
8. **Aspects loaded dynamically**: Always `_load_aspects()` (glob `personalities/*.json`). Never hardcode aspect list.
9. **Default aspect is Morrigan**: `_default_aspect()` returns Morrigan. Engineering/code is primary use.
10. **`systemPromptAddition` is never truncated**: Injected in full into system head for active aspect.

### Tool / Config
11. **Config always via `runtime_safety.load_config()`**: Never read `runtime_config.json` directly. This ensures hardware-derived defaults are merged.
12. **Tool calls bounded**: `max_tool_calls` and `max_runtime_seconds` must be enforced in every `autonomous_run` invocation. Research mode has separate (higher) limits.
13. **LLM serialized**: `llm_serialize_lock` (`RLock`) held for entire `autonomous_run`; one local LLM run at a time on single-user local deployments.
14. **Non-clinical psychology boundary**: Echo/Lilith must never assign DSM/ICD labels or clinical diagnoses to operator. `pin_psychology_framework_excerpt=true` default enforces reminder injection.
15. **`runtime_config.json` never committed**: Gitignored. Contains local paths and model filename.
16. **`layla.db` never committed**: Gitignored. Private memory.

### Architecture
17. **`fabrication_assist` not imported by main.py**: Boundary is intentional. Do not wire it into agent loop without deliberate integration decision.
18. **Geometry bridge recursion depth ≤ 3**: `MAX_BRIDGE_DEPTH=3` in executor; prevents infinite CAD bridge loops.

---

## 7. Assumptions

### System Assumptions
1. **Single operator, local deployment**: `llm_serialize_lock` is an RLock that serializes all LLM calls. This breaks under concurrent multi-user load. The production contract acknowledges this explicitly.
2. **Model is a local GGUF**: Default inference via `llama_cpp`. Remote OpenAI-compatible URL (`llama_server_url`) is an opt-in override. Model file path set in `runtime_config.json`.
3. **Python 3.11 or 3.12**: `pyproject.toml` enforces `>=3.11,<3.13`. Chroma/torch/sentence-transformers stack not validated on 3.13+.
4. **SQLite at repo root**: `layla.db` path is hardcoded in `db.py` as `Path(__file__).resolve().parent.parent.parent.parent / "layla.db"` (walks up from `agent/layla/memory/` to repo root).
5. **`agent/` is the working directory for server**: All relative imports and path resolution assume server runs from `agent/`.
6. **ChromaDB is optional**: System degrades gracefully to FTS5 + BM25 when `use_chroma=false` or ChromaDB unavailable.
7. **Sandbox root defaults to home directory**: `"sandbox_root": str(Path.home())` — all of `~` is accessible by default. Tighten in production.
8. **Game/fullscreen detection is best-effort**: `psutil.process_iter()` for study scheduler skip; may miss some games; always skips safely on psutil failure.

### Implicit Logic
9. **Conversation history is session-only**: `_history` deque (maxlen=20) in `main.py` is in-memory. `_conv_histories` dict in `shared_state.py` supports per-conversation-id multi-session deques. DB stores summaries after compression, not raw turns.
10. **Approval does not re-enter agent loop**: `POST /approve` runs the tool and returns. The UI must send a follow-up `/agent` request if another model turn is needed.
11. **Study scheduler requires activity within `scheduler_recent_activity_minutes`**: Default 1440 min (24h); so scheduler runs even if operator is away for less than a day. Game detection provides additional suppression.
12. **Nomic-embed-text-v1.5 is preferred embedder**: 768d. Falls back to all-MiniLM-L6-v2 (384d) if nomic unavailable. Dimension mismatch would break existing Chroma collections — collection should be rebuilt if embedder changes.
13. **Deliberation threshold**: Messages > 60 words OR containing deliberation keywords trigger multi-aspect deliberation mode. Otherwise standard single-aspect prompt.

---

## 8. Risks / Weak Points

### Critical
1. **LLM serialization bottleneck**: Single `RLock` means one LLM call blocks all others. Under concurrent UI tabs or multiple transport clients, requests queue behind each other. No queuing priority beyond `PRIORITY_CHAT` vs `PRIORITY_BACKGROUND` classification.
2. **Sandbox root defaults to `~`**: All files under home directory are in-scope. Operators who don't configure `sandbox_root` could allow reads/writes across their entire home. Should default to a narrower path like `~/layla-workspace`.
3. **`autonomous_run` is recursive via planner**: `execute_plan()` calls `autonomous_run()` for each plan step. Combined with `max_plan_depth`, this can still reach significant recursion depth. The `RLock` is reentrant, so same thread can re-enter. However, token/wall-time budgets are per-step, not cumulative.
4. **Pending approval file race**: `_write_pending()` reads, appends, rewrites `pending.json` without file lock. Concurrent approval requests from multiple transports could corrupt the file.
5. **ChromaDB dimension mismatch after embedder change**: If operator switches from nomic (768d) to MiniLM (384d) or vice versa, existing Chroma collection is incompatible and will error silently or fail queries. No migration path documented.

### Moderate
6. **`conversation_history` poisoning check on load**: `_load_history()` in `main.py` checks for junk assistant messages and clears history. This check is heuristic (`_is_junk_reply`, "you are layla" pattern). Edge cases exist where legitimate history could be cleared.
7. **Model router ContextVar isolation**: `_model_override_var` is a ContextVar, not thread-local. Under asyncio with thread pools (common in FastAPI), ContextVars propagate into spawned tasks correctly — but the RLock means only one runs at a time anyway. If threading model changes, this assumption breaks.
8. **Tool loop detection is per-run only**: `_recent_exact_calls` set is per `autonomous_run` invocation. It does not persist across requests. Repeat identical requests across separate `/agent` calls are not detected.
9. **Plugin loading on every startup**: `load_plugins()` in lifespan scans `plugins/` directory. No caching across restarts. On large plugin directories this adds startup latency.
10. **`write_file_explosion_factor`**: File size explosion guard (new_size > existing_size * factor) requires file to already exist. First write of any file has no size check.
11. **Mission worker runs every 2 minutes regardless of activity**: Unlike study scheduler, `_mission_worker_job` does not check `_last_activity_ts`. This is appropriate for long-running missions but means DB queries always run even when idle.

### Low / Cosmetic
12. **`_ASPECTS_CACHE_TTL = 60s`**: If an operator edits a personality JSON, the change takes up to 60s to propagate. `reload_aspects()` exists to force-reload but is not exposed via API.
13. **`runtime_config.example.json` may drift from `runtime_safety.py` defaults**: No automated check that all keys in the example match the defaults dict.
14. **`version.py` hardcoded to "1.0.0"**: No automated version bump mechanism. CHANGELOG.md is the human-maintained alternative.

---

## 9. Expansion Points

### Designed for Growth
1. **New tools**: Add function to `layla/tools/registry.py`, add to `TOOLS` dict with `dangerous`, `require_approval`, `risk_level`. No restart if server hot-reloads; restart otherwise.
2. **New aspects**: Create `personalities/<id>.json` with required fields. Glob-loaded automatically on restart. No code changes needed.
3. **Plugin system**: `plugins/<name>/plugin.yaml` — auto-loaded at startup via `plugin_loader.py`. Can register new tools, skills, capabilities.
4. **New knowledge**: Drop `.md`/`.txt`/`.pdf` in `knowledge/`. Re-indexed automatically on startup when fingerprint changes (or manually via `/workspace/index`).
5. **New transports**: Extend `transports/base.py` or add a new transport module. Pair via `/pair` endpoint; allowlist via `transport_allowlist` config.
6. **New capabilities**: `capability_discovery` → `integration_sandbox` → `benchmark_suite` → `capabilities/registry` pipeline. Can be triggered automatically when `benchmark_on_load` enabled.
7. **New geometry ops**: Add a new Pydantic model to `layla/geometry/schema.py` as a discriminated union member; add handling in the appropriate backend.
8. **New DB tables**: Add `CREATE TABLE IF NOT EXISTS` in `_migrate_impl()` plus any needed `ALTER TABLE` blocks for additive evolution.
9. **New study domains**: Add domain to `layla/memory/capabilities.py` domain registry; seed via `seed_self_training_plans.py`.
10. **Remote API expansion**: `remote_enabled`, `remote_allow_endpoints`, `remote_mode` (observe|interactive) already implemented in `main.py` auth middleware.

### Architecture Growth Paths
- **Multi-user**: Replace `RLock` with a per-request queue + worker pool. Add auth middleware beyond IP-based localhost.
- **Multi-agent**: `multi_agent_orchestration_enabled` + `services/task_graph.py` parallel roles already scaffolded. Wire to real parallel LLM runs when multiple GGUFs or remote endpoints available.
- **RL feedback loop**: `tool_outcomes` + `usefulness_score` + `capability_events` already capture data; missing the policy gradient or preference learning step.
- **OpenTelemetry**: Replace/supplement `services/observability.py` structured logging with OTLP export.
- **Fabrication kernel integration**: `fabrication_assist/assist/runner.py` `BuildRunner` stub pattern is the integration point. Implement a real runner and connect via tool in `layla/tools/registry.py`.

---

## 10. File-Level Index (Condensed)

### Core Agent Runtime
| File | Purpose |
|------|---------|
| `agent/main.py` | FastAPI app, lifespan (DB migrate, plugin load, scheduler, prewarm), all HTTP routes, /ui serving |
| `agent/agent_loop.py` | `autonomous_run()`, `stream_reason()`, `_build_system_head()`, `_llm_decision()`, `_save_outcome_memory()`, junk-reply detection |
| `agent/orchestrator.py` | `select_aspect()` (keyword+embedding), `build_deliberation_prompt()`, `build_standard_prompt()`, `should_deliberate()` |
| `agent/runtime_safety.py` | `load_config()` (TTL-cached), `_hardware_derived_defaults()`, `is_protected()`, `inside_sandbox()` indirect via registry, identity/knowledge loaders |
| `agent/shared_state.py` | Shared refs: `_history` deque, `_conv_histories`, pending, touch_activity, last commit |
| `agent/decision_schema.py` | `AgentDecision` Pydantic model, `parse_decision()` normalizer |
| `agent/config_schema.py` | `EDITABLE_SCHEMA`, `SETTINGS_PRESETS` (potato), settings API helpers |
| `agent/version.py` | `__version__ = "1.0.0"` |

### Routers
| File | Purpose |
|------|---------|
| `agent/routers/agent.py` | `POST /agent` (fast paths, autonomous_run, SSE streaming), `POST /learn/`, `GET /memories` |
| `agent/routers/approvals.py` | `POST /approve` (idempotent), `GET /pending` |
| `agent/routers/study.py` | Wakeup, study plans CRUD, presets, initiative rules, suggestions, derive_topic |
| `agent/routers/research.py` | Research mission endpoints: create, status, resume |

### Tools
| File | Purpose |
|------|---------|
| `agent/layla/tools/registry.py` | All 109 tools: `write_file`, `read_file`, `list_dir`, `shell`, `run_python`, `apply_patch`, git tools, search tools, memory tools, geometry tools, web tools, etc. Sandbox enforcement. |
| `agent/layla/tools/domains/` | Domain-grouped tool implementations (analysis, automation, code, data, file, general, geometry, git, memory, system, web) |
| `agent/layla/tools/web.py` | Web tool implementations |

### Memory
| File | Purpose |
|------|---------|
| `agent/layla/memory/db.py` | SQLite schema (`_migrate_impl`), FTS5 virtual table + triggers, all DB access functions; 15+ tables |
| `agent/layla/memory/vector_store.py` | ChromaDB + nomic-embed-text-v1.5; 2-stage retrieval (vector+BM25→top20, rerank→top10, cross-encoder→top k); HyDE; parent-doc; confidence+recency boost |
| `agent/layla/memory/distill.py` | `score_learning_content()`, `passes_learning_quality_gate()`, Jaccard dedup |
| `agent/layla/memory/capabilities.py` | Capability domain registry, `get_next_plan_for_study()`, `record_practice()`, `run_learning_validation()` |
| `agent/layla/memory/memory_graph.py` | Knowledge graph operations |

### Services
| File | Purpose |
|------|---------|
| `services/llm_gateway.py` | `run_completion()`, `prewarm_llm()`, `_get_llm()` (multi-GGUF path cache), ContextVar model override, token usage tracking |
| `services/context_manager.py` | `build_system_prompt()` (token-budgeted), `summarize_history()` (at 75% n_ctx) |
| `services/context_budget.py` | Per-section token limits: identity 400, memory 800, knowledge 800, graph 200, workspace 400 |
| `services/retrieval.py` | Unified retrieval: vector*0.5+BM25*0.3+graph*0.2+conf*0.1; parallel; MAX_K=5 cap |
| `services/planner.py` | `create_plan()` (3-6 steps, LLM-generated), `should_plan()`, role hints, tool reliability hints |
| `services/task_graph.py` | `TaskNode`, `TaskGraph`, `GraphExecutor`; adaptive parallelism via psutil |
| `services/mission_manager.py` | `create_mission()`, `execute_next_step()`; APScheduler integration |
| `services/reasoning_classifier.py` | `classify_reasoning_need()` heuristic: none\|light\|deep; `stabilize_reasoning_mode()` |
| `services/cognitive_workspace.py` | Tree-of-thought: 3 approaches → evaluate → choose; `strategy_hint` injection |
| `services/model_router.py` | `classify_task_for_routing()` → coding\|reasoning\|chat\|default; MODEL_ALIASES |
| `services/system_optimizer.py` | `get_effective_config()` runtime overrides; metrics collection; never persists |
| `services/output_polish.py` | `polish_output()`: code block protection, cleanup |
| `services/inference_router.py` | Multi-backend: llama_cpp, openai_compatible (vLLM), ollama; fallback URLs |
| `services/graph_reasoning.py` | spaCy NER + networkx BFS for query graph expansion; `graph_cache.py` TTL=300s |
| `services/hardware_detect.py` | CPU, RAM, GPU, VRAM, acceleration backend, machine tier |
| `services/model_recommender.py` | Rule-based model size/quantization from hardware |
| `services/model_manager.py` | list_models, install_model, benchmark_model |
| `services/llm_gateway.py` | (see above) |
| `services/stt.py` | faster-whisper STT; `detect_voice_mode`, `transcribe_streaming`, `prewarm` |
| `services/tts.py` | kokoro-onnx TTS; pyttsx3 fallback; configurable `tts_voice`, `tts_speed` |
| `services/browser.py` | Playwright browser; optional persistent profiles |
| `services/plugin_loader.py` | Scan `plugins/*/plugin.yaml`; register skills, tools, capabilities |
| `services/code_intelligence.py` | `search_codebase()`, `search_workspace()` via workspace_index |
| `services/workspace_index.py` | tree-sitter: functions/classes/imports/call graph; `build_workspace_graph()`; semantic codebase search |
| `services/style_profile.py` | Tone, response style, topics; embeddings+clustering; `update_profile_from_interactions()` |
| `services/reflection_engine.py` | Post-task what-worked/failed/improve → learnings |
| `services/knowledge_distiller.py` | `distill_learnings_to_insights()` periodic compression (60 min scheduler job) |
| `services/curiosity_engine.py` | Identify knowledge gaps; generate curiosity suggestions |
| `services/experience_replay.py` | Review tool outcomes + reflections for planning heuristics |
| `services/personal_knowledge_graph.py` | Unified graph: timeline, projects, goals, identity |
| `services/reasoning_strategies.py` | `get_strategy_for_task()` multi-strategy hints for complex goals |
| `services/tool_output_validator.py` | Normalize + annotate tool return dicts (hygiene) |
| `services/tool_loop_detection.py` | `push_and_evaluate()`, `exact_call_key()` — per-run duplicate suppression |
| `services/tool_args.py` | Validate `args` dict for selected tools when `tool_args_validation_enabled` |
| `services/observability.py` | Structured logging: agent_decision, tool_call, retrieval_cache; feeds performance_monitor |
| `services/performance_monitor.py` | Runtime metrics: tool latency, retrieval, token throughput |
| `services/dependency_recovery.py` | Structured missing-dep hints; optional pip install (allowlisted) |
| `services/auto_updater.py` | `apply_update()`: git pull + dep sync; dirty tree check; `restart_required` |
| `services/capability_discovery.py` | PyPI, GitHub, HuggingFace candidate scan |
| `services/integration_sandbox.py` | Temp venv isolation for candidate testing |
| `services/benchmark_suite.py` | Latency/throughput/memory benchmarks for capabilities |
| `services/sandbox_validator.py` | Import check + benchmark before enabling capability |
| `services/completion_cache.py` | In-memory LRU: key=routing_tag+model+temp+max_tokens+prompt |
| `services/response_cache.py` | Short response cache for near-identical queries |
| `services/retrieval_cache.py` | TTL cache for retrieval results (60s default) |
| `services/http_response_cache.py` | HTTP fetch cache (TTL, max entries configurable) |
| `services/agent_roles.py` | Role-specific tool hints for planner (researcher, debugger, memory_curator) |
| `services/shell_sessions.py` | `shell_session_start`, `shell_session_manage` — persistent shell sessions |
| `services/markdown_skills.py` | Load `SKILL.md` files from `skills/` as tool-callable skills |
| `services/health_snapshot.py` | Snapshot helper for /health endpoint |
| `services/project_discovery.py` | `run_project_discovery()` → LLM-based opportunity detection; `GET /project_discovery` |
| `services/resource_manager.py` | CPU/RAM/GPU tracking; `schedule_slot()`, `classify_load()`, `PRIORITY_*` constants |
| `services/context_builder.py` | Extracted context assembly logic from agent_loop |
| `services/decision_engine.py` | Extracted decision logic from agent_loop |
| `services/failure_recovery.py` | `_classify_failure_and_recovery()`, `_format_recovery_hint_for_prompt()` |
| `services/sandbox/python_runner.py` | `run_python` implementation: temp dir, timeout, optional RLIMIT_AS |
| `services/sandbox/shell_runner.py` | `shell` implementation: blocklist, allowlist, timeout |

### Geometry
| File | Purpose |
|------|---------|
| `agent/layla/geometry/schema.py` | `GeometryProgram`, `GeometryOp` discriminated union (Pydantic) |
| `agent/layla/geometry/executor.py` | `execute_program()` + sandbox check + backend dispatch |
| `agent/layla/geometry/backends/base.py` | `ExecutionContext`, `StepResult` base classes |
| `agent/layla/geometry/backends/ezdxf_backend.py` | DXF output via ezdxf |
| `agent/layla/geometry/backends/cadquery_backend.py` | STEP/STL via cadquery |
| `agent/layla/geometry/backends/openscad_backend.py` | Render STL via openscad CLI |
| `agent/layla/geometry/backends/mesh_backend.py` | Mesh info via trimesh |
| `agent/layla/geometry/bridges/http_cad_bridge.py` | HTTP CAD bridge; URL allowlist; depth limit |

### Capabilities
| File | Purpose |
|------|---------|
| `agent/capabilities/registry.py` | `vector_search`, `embedding`, `reranker`, `web_scraper`, `llm_model_coding` implementations; priority: config > benchmark > default |

### Personalities
| File | Purpose |
|------|---------|
| `personalities/morrigan.json` | Engineer. Default aspect. `decision_bias: ["efficient"]` |
| `personalities/nyx.json` | Researcher. Knowledge depth. |
| `personalities/echo.json` | Companion/mirror. Pattern tracking. Long-term growth. |
| `personalities/eris.json` | Chaos/creativity. Frame-breaking. |
| `personalities/lilith.json` | Authority/sovereign. NSFW register. `will_refuse: false` |
| `personalities/cassandra.json` | Oracle/reactive. Unfiltered immediate reaction. |

### Fabrication Assist (standalone)
| File | Purpose |
|------|---------|
| `fabrication_assist/assist/session.py` | `AssistSession` dataclass; JSON persistence; structure guards |
| `fabrication_assist/assist/schemas.py` | Pydantic schemas for fabrication job + parameters |
| `fabrication_assist/assist/runner.py` | `BuildRunner` abstract class; `StubRunner` stub (CI/test only) |
| `fabrication_assist/assist/echo_kernel.py` | Echo subprocess kernel for testing |
| `fabrication_assist/assist/layla_lite.py` | `assist()` function: Layla-guided explanation via LLM |
| `fabrication_assist/assist/explain.py` | Explanation generation for fabrication steps |
| `fabrication_assist/assist/variants.py` | Parameter variant generation |

### External Surfaces
| File | Purpose |
|------|---------|
| `cursor-layla-mcp/server.py` | MCP stdio server; `chat_with_layla`, approvals, learn, study tools; `LAYLA_BASE_URL` env |
| `layla.py` | CLI: `ask`, `wakeup`, `approve`, `pending`, `study`, `learn` → httpx to :8000 |
| `discord_bot/bot.py` | Full Discord bot: voice, TTS, music, `/note`, `/ask` |
| `transports/slack_bot.py` | Slack Socket Mode transport |
| `transports/telegram_bot.py` | Telegram polling transport |
| `transports/base.py` | Allowlist enforcement, `/pair` endpoint, `LAYLA_TRANSPORT_ALLOWLIST` |

### Tests
| File | Purpose |
|------|---------|
| `agent/tests/test_agent_loop.py` | classify_intent, decision parsing |
| `agent/tests/test_north_star.py` | Project context lifecycle, file understanding extensions |
| `agent/tests/test_approval_flow.py` | Approval gate: pending, approve, idempotency |
| `agent/tests/test_sandbox.py` | Sandbox containment |
| `agent/tests/test_golden_flow_http.py` | Full HTTP path: POST /agent → approval → approve → follow-up |
| `agent/tests/test_fabrication_assist*.py` | 5 fabrication test files: core, runner, CLI, session edges, doc links |
| `agent/tests/test_geometry_*.py` | Geometry schema, executor, bridge security |
| `agent/tests/test_reasoning_classifier.py` | none/light/deep classification |
| `agent/tests/test_inference_router.py` | Backend routing |
| `agent/tests/test_dual_model_routing.py` | Dual GGUF model selection |
| `agent/tests/test_task_graph.py` | Task dependency graph execution |
| `agent/tests/test_capability_routing.py` | Routing consistency, missing model fallback |
| `agent/tests/e2e_ui/test_ui_smoke.py` | Playwright browser: UI loads, panels open |
| `agent/tests/conftest.py` | Shared fixtures |

### Config / CI
| File | Purpose |
|------|---------|
| `.github/workflows/ci.yml` | CI: test (3.11+3.12), e2e-ui (Playwright), lint (ruff) |
| `pyproject.toml` | Build config, ruff rules, pytest markers, packages |
| `agent/runtime_config.example.json` | Annotated config template |
| `agent/pytest.ini` | (delegated to pyproject.toml `[tool.pytest.ini_options]`) |

### Documentation (high-signal)
| File | Purpose |
|------|---------|
| `LAYLA_NORTH_STAR.md` | Canonical vision §1-§20. Never edit unless operator asks. |
| `AGENTS.md` | AI ops manual: rules, repo map, code style, how-to |
| `ARCHITECTURE.md` | One-page request flow + state map |
| `docs/GOLDEN_FLOW.md` | Request lifecycle, approval semantics |
| `docs/PRODUCTION_CONTRACT.md` | Operational guarantees mapped to code |
| `docs/IMPLEMENTATION_STATUS.md` | §§ implementation status + platform tables |
| `docs/ETHICAL_AI_PRINCIPLES.md` | Ethics framework; §11 non-clinical boundary critical |
| `docs/CONFIG_REFERENCE.md` | All config keys annotated |
| `docs/OPERATOR_PSYCHOLOGY_SOURCES.md` | Psychology knowledge tiers; non-clinical policy |
| `docs/FABRICATION_ASSIST.md` | Fabrication assist boundary; BuildRunner integration checklist |
| `docs/RULES.md` | Naming, forbidden patterns, AI and human rules |
| `docs/RELEASE_CHECKLIST.md` | Pre-publish verification steps |
| `docs/RUNBOOKS.md` | How-to: add tools, aspects, knowledge |
| `PROJECT_BRAIN.md` | Stable summary; read before deep scans |
| `VALUES.md` | Sovereignty, privacy, anti-surveillance, solidarity |

---

## Change Log

| Date | Author | Description |
|------|--------|-------------|
| 2026-03-23 | Claude Sonnet 4.6 (automated analysis) | Initial MAX-DEPTH analysis: full repo read (150+ files), all core Python source, all major docs, test coverage, CI config. Established canonical system description, invariants, risks, expansion points, and file index. Branch: claude/xenodochial-feistel at commit d937bd7. |
