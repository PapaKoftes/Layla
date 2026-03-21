# Architecture — One-Page Overview

> For a **stable system summary** (before deep scans), see **`PROJECT_BRAIN.md`**.  
> For the full AI operations manual (file map, rules, style guide), see **`AGENTS.md`**.  
> **Production guarantees** (determinism boundaries, cost caps, safety, observability): **`docs/PRODUCTION_CONTRACT.md`**.  
> **Canonical lifecycle** (request → tool → approval → memory): **`docs/GOLDEN_FLOW.md`**.  
> **Subsystem technical depth:** **`docs/MODULE_SWEEP_STATUS.md`** (registry) and linked **`docs/*_MODULE_SECOND_SWEEP.md`** per cluster.

---

## Pinned versions and paths

- **Python**: **3.11 or 3.12 only** (`requires-python` in `pyproject.toml`; CI tests 3.11–3.12). Dependencies: `agent/requirements.txt`.
- **Database**: SQLite at **repo root** `layla.db`. All persistent memory (learnings, study_plans, wakeup_log, audit, aspect_memories, project_context, capabilities, **telemetry_events**) lives here.
- **Config**: `agent/runtime_config.json` (gitignored). Template at `agent/runtime_config.example.json`.
- **Model**: `models/<filename>.gguf` (gitignored). Set `model_filename` in config.

---

## Request flow

```
Client
  → HTTP → FastAPI (agent/main.py, port 8000)
  → Router dispatch:
      /agent, /learn/          → routers/agent.py    → agent_loop.autonomous_run()
      /research_mission        → routers/research.py → agent_loop (research_mode=True)
      /study_plans, /wakeup    → routers/study.py
      /approve, /pending       → routers/approvals.py
      /voice/transcribe        → services/stt.py     (faster-whisper)
      /voice/speak             → services/tts.py     (kokoro-onnx)
      /health, /health?deep=true, /health/deps, /usage, /undo, /version, /update/* → main.py (inline; `active_model`, `effective_config`, `features_enabled`, `dependencies`; `model_loaded_status` may include `recovery` for missing GGUF or `llama_cpp`; `knowledge_index_*`; `effective_limits`; `cache_stats` + `response_cache_stats`; see `docs/PRODUCTION_CONTRACT.md`, `docs/GOLDEN_FLOW.md`)
      /settings, /settings/schema, /settings/preset → main.py (schema-driven UI + named config merges, e.g. potato preset)
      /knowledge/ingest, /knowledge/ingest/sources → main.py (doc ingestion)
      /workspace/index         → main.py (semantic codebase indexing)
      /v1/*, /ui               → main.py (inline)
```

**Discord bot** (optional): `discord_bot/` — full bot with voice, TTS, music. Connects to localhost:8000 for chat. See `discord_bot/README.md`.

**Slack / Telegram** (optional): `transports/` — Socket Mode Slack and Telegram polling; same `/agent` bridge as Discord.

**Transport inbound policy** (optional, OpenClaw-style): `transports/base.py` — env `LAYLA_TRANSPORT_ALLOWLIST`, `LAYLA_TRANSPORT_PAIRING_SECRET` (`/pair`), config `transport_allowlist`, `transport_require_allowlist`. Paired ids: repo-root `.layla_transport_paired.json` (gitignored). See `docs/OPENCLAW_ALIGNMENT.md`, `docs/OPENCLAW_BRIDGE.md`. **Integrations sweep:** `docs/INTEGRATIONS_MODULE_SECOND_SWEEP.md`.

**Operator surfaces (local):** **`cursor-layla-mcp/server.py`** — MCP stdio server; `LAYLA_BASE_URL` (default `http://127.0.0.1:8000`) → `POST /agent`, `/approve`, `/pending`, etc. **`layla.py`** (repo root) — CLI via httpx to `http://localhost:8000`. Deep pass: `docs/MCP_MODULE_SECOND_SWEEP.md`.

**Geometry subsystem:** `agent/layla/geometry/` — versioned `GeometryProgram`, sandboxed `execute_program()`, optional HTTP CAD bridge (`geometry_external_bridge_url`). Sweep: `docs/GEOMETRY_MODULE_SECOND_SWEEP.md`.

**Sandbox runners** (optional paths): `services/sandbox/shell_runner.py` and `services/sandbox/python_runner.py` — timeouts and optional shell allowlist; wired from `shell` / `run_python` tools.
**Fast chat path**: `routers/agent.py` short-circuits trivial greeting/ack turns and can serve cached short responses via `services/response_cache.py` when enabled.

**Structured tool args** (optional): `services/tool_args.py` validates `decision["args"]` for selected tools when `tool_args_validation_enabled`.

**OpenClaw-style core emulation** (optional): `services/tool_policy.py` (`tools_profile`, `tools_allow`/`tools_deny`, `group:*`, `tools_by_provider`) + intent filter + pre-exec guard in `agent_loop`; `services/tool_loop_detection.py` (`push_and_evaluate(..., reasoning_mode=)`, `exact_call_key`); `services/tool_output_validator.py` (post-tool dict hygiene); per-run exact duplicate tool invocation suppression in `agent_loop`; `services/shell_sessions.py` (`shell_session_start` / `shell_session_manage`); `services/http_response_cache.py`; `services/markdown_skills.py` + repo `skills/`; `inference_fallback_urls` + non-stream retries in `inference_router.py`; `browser_persistent_profiles` in `services/browser.py`. See `docs/OPENCLAW_ALIGNMENT.md`.

**agent_loop.autonomous_run():**
1. `runtime_safety.load_config()` — TTL-cached, hot-path safe
1a. **`services/reasoning_classifier.classify_reasoning_need()`** — heuristic `none` | `light` | `deep`; stored as `state["reasoning_mode"]`, returned in API/UI. On `performance_mode: low`, `deep` is capped to `light`. **`none`** skips planner (`should_plan` short-circuited); **`light`** and **`none`** skip streaming self-reflection (`stream_reason` `skip_self_reflection`).
1b. **Task model routing** (when `tool_routing_enabled` and `model_router.is_routing_enabled()`): `classify_task_for_routing(goal, context, cfg)` → `set_model_override` so `llm_gateway` loads task GGUFs via `resolve_model_path`. Dual-model mode: when `resource_manager.should_use_dual_models()` (free RAM ≥ `dual_model_threshold_gb` or `force_dual_models`), `_effective_model_filename()` picks chat vs agent basenames via `resolve_dual_model_basenames()` (`chat_model_path` / `agent_model_path` or `chat_model` / `coding_model` / `model_filename`). Every `run_completion()` sets a routing-prompt ContextVar so `_effective_model_filename()` applies the same classification when override is unset (internal JSON/decision prompts are excluded). Otherwise `select_model` / `get_best_llm_filename_for_task` apply. Multi-model cache `_llm_by_path`; serialize lock is `RLock`. Optional `completion_cache_enabled` caches non-stream dict responses briefly; cache key includes **model basename + temperature + max_tokens** + routing tag + prompt; `completion_cache_max_entries` caps size. **`GET /health`** and **`GET /platform/models`** expose `model_routing` (routing flags + resolved basenames).
2. `orchestrator.select_aspect()` — keyword-based, loads `personalities/*.json`
3. `_build_system_head()` — identity + knowledge RAG (BM25+vector+FTS5+rerank) + learnings + CoT; passes through `context_manager.build_system_prompt()` for token budgets and deduplication
4. **Cognitive workspace** (if `enable_cognitive_workspace`): generate approaches → evaluate → choose best; inject `strategy_hint` into decision prompt and plan context
5. **Planning** (if `should_plan`): `create_plan` → `execute_plan`; each step runs `autonomous_run` recursively
6. **Decision loop** (up to `max_tool_calls`):
   - `_llm_decision()` → parse JSON `{action, tool_name, objective_complete, ...}` (`decision_schema.parse_decision`; `action` may be `none` | `tool` | `reason`)
   - If `action=none`: append no-op step and continue
   - If `action=tool`: `registry.TOOLS[name]()` — gated by `allow_write`/`allow_run` + approval; optional `max_patch_lines` gate for `apply_patch`
   - If `action=reason` or `objective_complete`: `_completion()` → stream final reply
7. Optional self-reflection (`enable_self_reflection`) — score + rewrite if < 7/10
8. `_save_outcome_memory()` — distill and store outcome; reflection engine (what worked/failed/improve)
9. **Local telemetry** (`telemetry_enabled`, default on): `services/telemetry.log_event()` → SQLite `telemetry_events` (task type, reasoning_mode, model, latency, success, performance_mode). Trivial `reasoning_mode=none` rows skipped unless `telemetry_log_trivial`. No network.

**Performance modes:** `system_optimizer.get_effective_config()` applies `performance_mode` (`low` / `mid` / `high` / `auto`) before CPU/RAM pressure tiers. Omitted key = `mid`. Explicit `auto` uses `hardware_detect.detect_hardware()` with VRAM/RAM numeric thresholds (GPU VRAM: 6 GB and 12 GB boundaries; CPU-only: system RAM 8 GB and 24 GB boundaries). Never writes to `runtime_config.json`.

**Streaming final reply:** When `stream_final` returns `stream_pending`, `routers/agent.py` calls `stream_reason(..., model_override=..., skip_self_reflection=...)` so task routing matches the main run and reflection respects `reasoning_mode` (ContextVar is cleared after `autonomous_run` returns). SSE `done` payloads include `reasoning_mode`.

**LLM run lock scope:** `services/llm_gateway.llm_serialize_lock` is held for the entire `autonomous_run` lifecycle (not just completion calls) to avoid concurrent local LLM runs.

**First-run UI:** `GET /setup_status` (`performance_mode`, `model_valid`, `ready`), `GET /setup/models` (catalog + `recommended_key`) — setup overlay in `agent/ui/index.html`. **`POST /agent`** returns `error: no_model`, `action: open_setup` when the model is missing.

**Capability LLM routing:** `capabilities/registry.py` includes `llm_model_coding` (Magicoder vs default); `model_router.select_model()` consults `get_active_implementation("llm_model_coding", cfg)` and stored benchmarks. **`models` config block** and `coding_model` remain the source of GGUF filenames.

**Approval:** tool returns `approval_required` → queued in `shared_state.pending` → `POST /approve {"id": uuid}` → proceed

**Capability parity (Layla plan):** Auto lint/test-fix loop, image context in agent, voice-to-code TUI, token usage (`/usage`), multi-model UI (`model_override`), git auto-commit + `/undo`, reasoning mode, `write_files_batch`, TUI `/add`/`/run`/`/diff`, semantic codebase index (`search_workspace` + `POST /workspace/index`).

---

## Where state lives

| What | Where |
|---|---|
| Learnings, study plans, wakeup log, audit | SQLite `layla.db` (repo root) |
| Run telemetry (local) | SQLite `layla.db` → `telemetry_events` |
| FTS5 full-text search index | Virtual table in `layla.db` (auto-sync triggers) |
| Semantic memory vectors | ChromaDB `agent/chroma/` (config-driven) |
| BM25 index | In-memory, rebuilt from learnings on count change |
| Conversation history | `shared_state` in-memory deque |
| Conversation summaries | SQLite `layla.db` (conversation_summaries + embedding_id) — retrieval participation |
| Relationship memory | SQLite `layla.db` (relationship_memory + embedding_id) — companion context |
| Timeline events | SQLite `layla.db` (timeline_events) — personal timeline memory |
| User identity | SQLite `layla.db` (user_identity) — verbosity, humor, formality, response length |
| Episodes | SQLite `layla.db` (episodes, episode_events) — episodic memory grouping |
| Tool outcomes | SQLite `layla.db` (tool_outcomes) — tool reliability learning |
| Goals | SQLite `layla.db` (goals, goal_progress) — long-term goal tracking |
| Pending approvals | `shared_state.pending` list + audit in DB |
| Knowledge index | ChromaDB `agent/chroma/` (collection: `knowledge`) |
| Research lab / output | `agent/.research_lab/`, `agent/.research_output/`, `agent/.research_brain/` |
| Config | `agent/runtime_config.json` |

---

## Scheduler and wakeup

- **Scheduler**: APScheduler background job advances study plans only when `touch_activity` is recent (touched by `/agent`, `/wakeup`, `/learn/`, `/ui`). Config: `scheduler_study_enabled`, `scheduler_interval_minutes`, `scheduler_recent_activity_minutes`.
- **Wakeup**: `GET /wakeup` marks activity, logs session, returns last wakeup time, active study plans, and optional "what was studied" summary.

---

## Key files

| File | Role |
|---|---|
| `agent/main.py` | FastAPI app, lifespan, all routes, `/ui`, `/v1`, `/health`, GZip middleware |
| `agent/agent_loop.py` | `autonomous_run()` orchestrator. Delegates to decision_engine, failure_recovery, tool_orchestrator, context_builder |
| `agent/orchestrator.py` | Aspect selection, deliberation prompt builder |
| `agent/runtime_safety.py` | Config load (TTL-cached), file caching, hardware probe, sandbox validation |
| `agent/shared_state.py` | Shared refs: history deque, pending approvals, touch_activity, audit |
| `agent/decision_schema.py` | Pydantic decision model, `parse_decision()` |
| `agent/layla/tools/registry.py` | All tools + `TOOLS` dict. Add tools here. |
| `agent/layla/memory/db.py` | SQLite schema, `migrate()`, all DB access, FTS5 |
| `agent/layla/memory/vector_store.py` | Two-stage retrieval: vector+BM25→top 20, light rerank→top 10, cross-encoder→top k. Config `retrieval_cross_encoder_limit`. ChromaDB, HyDE, parent-doc, confidence+recency boost |
| `agent/services/context_budget.py` | Token budgets per section (identity, memory, knowledge, graph, workspace) |
| `agent/services/context_manager.py` | Prompt assembly with budgets, deduplication, conversation summarization |
| `agent/services/llm_gateway.py` | `run_completion()`, `prewarm_llm()`, multi-path `_get_llm()` + `RLock`; exported serialize lock used for full `autonomous_run` serialization |
| `agent/services/model_router.py` | `classify_task`, `route_model`, `select_model`, `models{}` aliases, `reset_router_config_cache` |
| `agent/services/output_polish.py` | `polish_output()` final reply cleanup |
| `agent/services/inference_router.py` | Multi-backend routing: llama_cpp, openai_compatible (vLLM), ollama |
| `agent/services/graph_reasoning.py` | Entity extraction (spaCy) + graph expansion (networkx) for query context |
| `agent/services/cognitive_workspace.py` | Tree-of-thought: generate approaches (search/reasoning/tools) → evaluate → choose best; inject strategy_hint |
| `agent/services/workspace_index.py` | Semantic search + code intelligence (tree-sitter: functions, classes, imports, calls) |
| `agent/services/stt.py` | faster-whisper STT; detect_voice_mode, transcribe_streaming |
| `agent/services/tts.py` | kokoro-onnx TTS with pyttsx3 fallback; get_voice_options, configurable tts_voice |
| `agent/services/style_profile.py` | Tone, response style, topics; embeddings + clustering; updates db.style_profile |
| `agent/services/browser.py` | Playwright browser automation |
| `agent/services/hardware_detect.py` | Hardware detection (CPU, RAM, GPU, tier) |
| `agent/services/model_recommender.py` | Model recommendation from hardware |
| `agent/services/model_manager.py` | Model list/install/benchmark |
| `agent/services/model_benchmark.py` | Tokens/sec benchmark on load |
| `agent/services/plugin_loader.py` | Load plugins from `plugins/` |
| `agent/layla/skills/registry.py` | Skills (named tool workflows) |
| `agent/routers/agent.py` | `POST /learn/`, `POST /agent` |
| `agent/routers/approvals.py` | `POST /approve`, `GET /pending` |
| `agent/routers/study.py` | `GET /wakeup`, `/study_plans` |
| `agent/ui/index.html` | Web UI: chat, aspect selector, panels (Health, Models, Knowledge, Plugins, Study, Memory, Research, Help); unified `/health` poller + `BroadcastChannel('layla-health-v1')` to sync header status across tabs |
| `agent/layla/geometry/executor.py` | `execute_program()`, `list_framework_status()` — sandbox + backends + optional `cad_bridge_fetch` |
| `cursor-layla-mcp/server.py` | Cursor MCP: `chat_with_layla`, approvals, learn/study tools → localhost FastAPI |
| `layla.py` | Operator CLI: `ask`, `wakeup`, `approve`, `pending`, `study`, … → httpx to agent |
| `personalities/*.json` | Aspect definitions. Loaded dynamically — never hardcode the list. |

---

## Sovereign platform subsystems

- **First-run installer**: `agent/install/` — `hardware_probe.py` (CPU, RAM, GPU, CUDA/ROCm/Metal), `model_selector.py` (catalog-based recommendation), `model_downloader.py` (huggingface_hub or urllib), `installer_cli.py` (interactive wizard). Models in `~/.layla/models/`. Config: `models_dir`, `resolve_model_path()` in `runtime_safety`.
- **Hardware detection**: `services/hardware_detect.py` — CPU, RAM, GPU, VRAM, acceleration backend, machine tier. Used by `runtime_safety`, `first_run`, `model_recommender`.
- **Model recommender**: `services/model_recommender.py` — recommends model size/quantization from hardware.
- **Model manager**: `services/model_manager.py` — list/install/benchmark models under `~/.layla/models/` (config: `models_dir`).
- **Skills**: `layla/skills/registry.py` — named workflows (analyze_repo, research_topic, etc.). Planner injects skill hints when `skills_enabled`.
- **Plugins**: `plugins/*/plugin.yaml` — auto-loaded at startup. Add skills and optional tools via `services/plugin_loader.py`.
- **Model benchmark**: `services/model_benchmark.py` — tokens/sec on load when `benchmark_on_load`.
- **Memory distillation**: `layla/memory/distill.py` — Jaccard + optional semantic clustering; `distill_rules()` for rule extraction.
- **Token budgeting**: `services/context_budget.py` — allocates token limits per prompt section (identity, memory, knowledge, graph, workspace). Used by `context_manager.build_system_prompt()`.
- **Context management**: `services/context_manager.py` — centralized prompt assembly with per-section token budgets (from context_budget), deduplication, conversation summarization, and observability. Summaries persist to `conversation_summaries` (with embeddings) for retrieval.
- **Graph reasoning**: `services/graph_reasoning.py` — spaCy entity extraction + networkx graph expansion. Query context expands via knowledge graph relationships. Integrated into `retrieval.retrieve_graph_context`. `services/graph_cache.py` caches expansion results (TTL 300s) to avoid repeated BFS.
- **Code intelligence**: `services/workspace_index.py` — tree-sitter extracts functions, classes, imports, call graph from Python. `extract_code_architecture()`, `get_architecture_summary()`, `build_workspace_graph()` (semantic dependency graph: files, functions, classes, imports; edges: calls, imports, inherits, depends_on, implements), `get_workspace_dependency_context(query)` for coding tasks. Injected into `_build_system_head` when coding keywords detected.
- **Parallel agent roles**: `services/task_graph.py` — `run_parallel_ready()`, `run_until_complete_parallel()` for concurrent execution of planner, researcher, executor, critic, memory_curator when dependencies permit. Adaptive parallelism: workers adjust dynamically by CPU/RAM (psutil).
- **Capability registry**: `capabilities/registry.py` — capability types (vector_search, embedding, reranker, web_scraper) with multiple implementations. Selection priority: 1) `capability_impls` config override, 2) best benchmark score, 3) default.
- **Capability discovery**: `services/capability_discovery.py` — `discover_candidate_libraries`, `fetch_pypi_candidates`, `fetch_github_candidates`; scans PyPI, GitHub, HuggingFace.
- **Integration sandbox**: `services/integration_sandbox.py` — temp venv, install candidate, compatibility tests, benchmarks; isolated from Layla runtime.
- **Benchmark suite**: `services/benchmark_suite.py` — latency, throughput, memory for vector_search, embedding, reranker, web_scraper; stores in `capability_implementations`.
- **Sandbox validator**: `services/sandbox_validator.py` — import check + benchmark before enabling a capability.
- **Performance monitor**: `services/performance_monitor.py` — runtime metrics (tool latency, retrieval, token throughput).
- **System optimizer**: `services/system_optimizer.py` — collects CPU, RAM, GPU, token throughput, tool latency, retrieval latency; applies adaptive runtime overrides (context size, parallel tasks, retrieval depth). Changes are runtime-only; never persist to `runtime_config.json`.
- **Observability**: `services/observability.py` — structured logging for agent_decision, tool_call, tool_result, retrieval_cache_hit/miss; records to performance_monitor for system_optimizer.

---

## Companion intelligence subsystem

1. **Relationship memory** — `db.relationship_memory` stores meaningful interaction summaries (user_event, timestamp, embedding_id). Populated when conversation is compressed. Injected into `_build_system_head` as "Recent relationship context".
2. **Timeline events** — `db.timeline_events` stores personal timeline (event_type, content, timestamp, importance). Populated on conversation compress. Injected as "Recent timeline".
3. **User identity** — `db.user_identity` stores long-term companion context (verbosity, humor_tolerance, formality, response_length, life_narrative_summary). Tools: `get_user_identity`, `update_user_identity`. Injected as "User/companion context".
4. **Style profile** — `services/style_profile.py` tracks tone, preferred response style, frequent topics via embeddings + clustering. Updates `db.style_profile`. Injected when `enable_style_profile` is true.
5. **Voice** — `stt.detect_voice_mode`, `stt.transcribe_streaming`; `tts.get_voice_options`, configurable `tts_voice` in runtime_config.
6. **Context injection** — `_build_system_head` injects: relationship memory, timeline events, user identity, conversation summaries, style profile (writing/coding/reasoning/structuring + **collaboration** heuristic snapshot when `enable_style_profile`), personal knowledge graph, reasoning strategies (for complex goals), active goals. Optional **`direct_feedback_enabled`** (blunt collaboration, non-clinical) and **`pin_psychology_framework_excerpt`** (Echo/Lilith pinned interaction-framework reminder). Reflective user phrasing widens knowledge RAG triggers in `_needs_knowledge_rag`.
7. **Reflection engine** — `services/reflection_engine.py`: after task completion, generate what worked/failed/could improve; store as learnings.
8. **Knowledge distiller** — `services/knowledge_distiller.py`: periodically compress learnings into higher-level insights.
9. **Tool outcome learning** — `layla.memory.db.tool_outcomes`: record success/latency; planner prefers higher-reliability tools.
10. **Goal engine** — `goals`, `goal_progress` tables; tools: add_goal, add_goal_progress, get_active_goals; integrated with project context.
11. **Curiosity engine** — `services/curiosity_engine.py`: identify knowledge gaps, suggest learning/exploration.
12. **Experience replay** — `services/experience_replay.py`: review tool outcomes and reflections for planning heuristics.
13. **Personal knowledge graph** — `services/personal_knowledge_graph.py`: unified graph (timeline, projects, goals, identity); used during retrieval.

---

## Runtime optimization system

1. **Metrics** — `system_optimizer.collect_metrics()` aggregates from `resource_manager` (CPU, RAM, GPU) and `performance_monitor` (token throughput, tool latency, retrieval latency, agent decision time).
2. **Adaptive config** — `system_optimizer.get_effective_config(base_cfg)` returns merged config with runtime overrides when CPU/RAM/GPU exceed thresholds. `agent_loop` uses this at run start.
3. **Instrumentation** — Tool registry wraps each fn with timing; `log_tool_result` records to performance_monitor. `_llm_decision` timed; `log_agent_decision` records. Retrieval cache hit/miss records retrieval latency.
4. **Health/doctor** — `GET /health` and `GET /doctor` include `system_optimizer` summary (metrics, performance with averages and recent values, overrides, parallel_tasks_suggested).

---

## Capability evolution pipeline

1. **Discovery** — `capability_discovery.discover_candidate_libraries(capability_name)` fetches candidates from PyPI (`fetch_pypi_candidates`), GitHub (`fetch_github_candidates`), HuggingFace.
2. **Sandbox** — `integration_sandbox.evaluate_candidate()` creates temp venv, installs package, runs compatibility tests, benchmarks. Isolated from Layla runtime.
3. **Benchmark** — `benchmark_suite.run_benchmark()` measures latency, throughput, memory for vector_search, embedding, reranker, web_scraper. Results stored in `capability_implementations`.
4. **Promotion** — `capabilities/registry.get_active_implementation()` selects: 1) `runtime_config.capability_impls` override, 2) best benchmark score, 3) default.

---

## Capability domain mapping

Layla is organized into 10 capability domains. Each maps to specific modules. See [docs/LAYLA_PREBUILT_PLATFORM.md](docs/LAYLA_PREBUILT_PLATFORM.md) for full detail.

| Domain | Modules | Notes |
|--------|---------|-------|
| Conversation Intelligence | orchestrator, context_manager, stt, tts, llm_gateway, style_profile | Aspect selection, RAG context, voice I/O, companion intelligence |
| Knowledge Intelligence | vector_store, db, retrieval, retrieval_cache, distill | ChromaDB, BM25, FTS5, HyDE |
| Code Intelligence | file_understanding, workspace_index (tree-sitter), registry (python_ast, grep_code, etc.) | Functions, classes, imports, call graph |
| Automation | browser, task_graph, planner, research_stages | Playwright, scheduling, research pipeline |
| Model Management | llm_gateway, model_manager, model_recommender, model_benchmark, model_router | Hardware-aware model selection |
| Agent Runtime | agent_loop, shared_state, decision_schema, mission_manager, routers | Decision loop, approval gate, tool dispatch |
| Skill Library | layla/skills/registry, plugin_loader, planner | Named workflows, plugin loading |
| Hardware Intelligence | hardware_detect, first_run, runtime_safety | CPU/RAM/GPU detection, first-run wizard |
| Self Improvement | study_service, self_improvement, capability_discovery, integration_sandbox, benchmark_suite, sandbox_validator, capabilities/registry, distill | Capability evolution pipeline; study plans; benchmarking |
| User Interface | ui/index.html, tui, cursor-layla-mcp, layla.py | Web UI, TUI, MCP, CLI |

---

## Platform UI components

Control center panels (right sidebar, tabbed):

| Panel | API | Content |
|-------|-----|---------|
| Health | GET /health | Status, model loaded, tools, learnings, study plans, CPU/RAM, `cache_stats` (completion cache hits/misses) |
| Models | GET /platform/models | Active model, installed .gguf list, catalog (jinx/dolphin/hermes/qwen), benchmarks |
| Knowledge | GET /platform/knowledge | Summaries, learnings, graph nodes, timeline, user identity |
| Plugins | GET /platform/plugins | Loaded plugins, skills added, tools added, errors |
| Projects | GET /platform/projects | Project context: goals, progress, blockers, last_discussed |
| Timeline | (via /platform/knowledge) | Timeline events (conversation summaries, milestones) |
| Study | GET /study_plans | Study plans, add/remove |
| Memory | (search) | Memory search via agent |
| Research | /missions, /mission/{id} | Mission tracker, research mission status |
| Help | — | Capabilities, usage hints |
