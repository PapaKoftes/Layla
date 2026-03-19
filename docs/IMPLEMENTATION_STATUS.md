# Implementation Status vs LAYLA_NORTH_STAR.md

This document maps each section of the North Star to code, tests, and verification so we never stray from the plan.

---

| § | North Star | Implementation | Tests / verification |
|---|------------|----------------|----------------------|
| 1 | Core purpose: partner system, grow with user, assist, structure, translate, improve, maintain identity | Identity in `.cursor/rules/layla-assistant.mdc`, `agent_loop.py` system head, learnings + style profile | E2E and agent loop tests |
| 2 | User reality: programming, fabrication, geometry, automation, docs, research, planning; focus on friction points | Morrigan prompt (planning, docs, Python, DXF→fabrication); fabrication domains + study plans | Study plans seeded; capabilities test |
| 3 | Project participation: project awareness, lifecycle (Idea→Planning→Prototype→Iteration→Execution→Reflection) | `project_context` table: project_name, domains, key_files, goals, **lifecycle_stage**, **progress**, **blockers**, **last_discussed**; `get_project_context` / `set_project_context`; injected in agent head; **GET/POST /project_context**, **GET /platform/projects** API | `test_north_star.py::test_project_context_lifecycle`, `test_platform_ui.py::test_platform_projects` |
| 4 | File ecosystem: geometry, fabrication, programming, documentation, visual — interpret intent | `agent/layla/file_understanding.py`: all North Star extensions; `analyze_file()`, `get_supported_extensions()` | `test_north_star.py::test_file_understanding_*` |
| 5 | Workflow translation: Geometry→Fabrication→Machine intent; DXF→machinable, parametric→geometry, Python→automation | Fabrication domains + dependencies; Morrigan/Nyx roles; file_understanding hints | Capability deps; study plans |
| 6 | Execution loop: Learn→Plan→Assist→Evaluate→Improve; applied learning | Study service, capability events, record_practice, reinforcement_priority, scheduler | `test_study_integration`, scheduler job |
| 7 | Learning judgment: usefulness, transferability, real-world impact; selective learning | `usefulness_score`, `learning_quality_score` on capability_events; `run_learning_validation`; weak reinforce & no cross-domain when < 0.3 | `record_practice` with usefulness; validation in study flow |
| 8 | Failure awareness: workflow breakdowns, planning gaps, execution issues; assist recovery | **Implemented:** `_classify_failure_and_recovery` sets structured `recovery_hint` (type, message, source); `_format_recovery_hint_for_prompt` stringifies at prompt assembly; `_run_verification_after_tool`; planning_gap, execution_issue, workflow_breakdown | `test_failure_classify_*`, `test_format_recovery_hint_for_prompt` |
| 9 | Documentation intelligence: technical→human translation; core strength | Writing domain, style profile, Morrigan “documentation” priority; study plans for writing | Study plans; style_profile in head |
| 10 | Initiative model: suggest improvements, propose projects, explore safely; gated | **Implemented:** Wakeup initiative (text-only, gated). Config `wakeup_include_initiative`; data-driven `INITIATIVE_RULES` + `_initiative_condition_matches` in study router; first matching rule wins | test_wakeup_initiative_suggestion, test_initiative_rule_ordering |
| 11 | Personality: Morrigan, Nyx, Echo, Eris, Lilith; Lilith governs autonomy | `personalities/*.json`; orchestrator; deliberation roster | Aspect selection tests |
| 12 | Decision system: feasibility, knowledge depth, alignment, creativity, risk; execution via Morrigan | `orchestrator.build_deliberation_prompt` with structured roles; CONCLUSION — MORRIGAN | Deliberation prompt format |
| 13 | Identity continuity: evolve, consistency, quirks; Echo tracks long-term growth | Echo prompt; style_profile; learnings; aspect_memories | Wakeup; Echo in deliberation |
| 14 | Autonomy: suggest, guide, organize; eventually initiate safely | **Implemented:** Same as §10 — wakeup initiative (one proactive suggestion when `wakeup_include_initiative` true); approval flow; study scheduler | Wakeup; approval required for write/run |
| 15 | Safety: Lilith gates file modification, autonomous execution, learning acceptance | Lilith systemPromptAddition; approval flow; usefulness gating for reinforcement | Refusal tests; approval API |
| 16 | Local-first: persistent, local; remote opt-in | **Implemented:** Config `remote_enabled`, `remote_api_key`, `remote_allow_endpoints`, `remote_mode` (observe \| interactive). Auth middleware: Bearer token for non-localhost; endpoint allowlist. Bind to localhost only unless `remote_enabled` (see docs/REMOTE_ARCHITECTURE.md). No autonomy added. | tests/test_remote.py |
| 17 | Toolchain awareness: format transitions, workflow dependencies, automation paths | file_understanding; project_context; fabrication deps | File + project context in head |
| 18 | Project discovery: detect opportunities, synthesize, evaluate feasibility | **Implemented:** `run_project_discovery()` in `agent/services/project_discovery.py`; timeout guard, strict JSON, safe fallback, max item length; **GET /project_discovery**; LLM via `services.llm_gateway` | test_project_discovery_returns_structure, test_project_discovery_malformed_completion_returns_safe_fallback |
| 19 | Long-term growth: capability, alignment, partnership | Capabilities + domains; learnings; study plans; usefulness-weighted growth | Capability events; seed plans |
| 20 | Ultimate goal: collaborative intelligence that grows, improves work, expands possibility | Whole system; North Star as single source of truth | Full E2E and integration tests |

---

## System is non-autonomous by design

- The system **does not** run tools, write files, or execute code without explicit user approval (approval flow).
- The system **does not** background itself, run cron jobs for agent actions, or perform autonomous runs triggered by remote calls.
- **Remote** (§16) only exposes the same HTTP API behind authentication and an endpoint allowlist; every tool run still requires approval when applicable. No additional autonomy is introduced.
- Study scheduler runs only when `scheduler_study_enabled` is true and only performs study-plan steps (read-only research style); it does not modify user files or run write/run tools without approval.

---

## Safe self-upgrade (post–North Star)

See [ETHICAL_AI_PRINCIPLES.md](ETHICAL_AI_PRINCIPLES.md) for the full ethical AI framework.

- **Approval flow**: All file writes, code execution, and high-impact actions require `layla approve <uuid>` or API approve.
- **add_learning**: Layla can remember preferences and corrections; stored in learnings.
- **Study plans + usefulness**: New knowledge reinforces only when `usefulness_score` ≥ 0.3; low-value learning does not propagate.
- **Lilith**: Gates autonomous execution and learning acceptance.
- **Changes by Layla**: Proposed edits go through approval; no self-modification without user approval.

---

---

## Sovereign platform (post–North Star)

| Subsystem | Implementation | Notes |
|-----------|----------------|------|
| Hardware detection | `services/hardware_detect.py` | CPU, RAM, GPU, VRAM, Metal/CUDA/ROCm, machine tier |
| Model recommender | `services/model_recommender.py` | Rule-based model size/quantization from hardware |
| Model manager | `services/model_manager.py` | list_models, install_model, benchmark_model, select_best_model |
| Skills layer | `layla/skills/registry.py` | analyze_repo, research_topic, write_python_module, etc. |
| Plugin system | `plugins/`, `services/plugin_loader.py` | plugin.yaml manifest, auto-register skills/tools |
| Agent roles | `planner.py` ROLE_TOOL_HINTS | researcher, debugger, memory_curator role hints |
| Model benchmark | `services/model_benchmark.py` | tokens/sec on first load when benchmark_on_load |
| Memory distillation | `layla/memory/distill.py` | Jaccard + optional semantic clustering, distill_rules() |
| Hardware-aware startup | `main.py` lifespan | Log hardware + recommendation when hardware_aware_startup |

---

## Phase 3 — Performance, adaptive reasoning, local telemetry

| Area | Implementation | Notes |
|------|----------------|-------|
| Completion cache key | `services/completion_cache.py`, `services/llm_gateway.py` | Key: routing tag + effective model + temperature + max_tokens + prompt; `completion_cache_max_entries` |
| Context budgets | `services/context_budget.py` | Single `pinned_context` entry in `DEFAULT_BUDGETS` (deduped) |
| Reasoning classifier | `services/reasoning_classifier.py` | `none` \| `light` \| `deep`; gates planner + streaming reflection; `reasoning_mode` on state and `/agent` JSON/SSE |
| Telemetry | `services/telemetry.py`, `db.telemetry_events`, `db.log_telemetry_event` / `get_recent_telemetry_events` | `telemetry_enabled` (default true); `telemetry_log_trivial` to log `reasoning_mode=none` runs; `suggest_optimization()` heuristic over last 50 events |
| Agent loop safety / hygiene | `services/tool_output_validator.py`, `agent_loop.py`, `services/tool_loop_detection.py`, `decision_schema.py` | Tool output normalization; per-run exact duplicate suppression; `push_and_evaluate(..., reasoning_mode=)` tightens default repeat stop in `none`/`light`; `action: "none"`; `max_patch_lines` before `apply_patch` |
| UI | `agent/ui/index.html` | `#reasoning-mode-badge` |

Tests: `tests/test_reasoning_classifier.py`.

---

## Power-user upgrade (phased)

| Area | Implementation | Notes |
|------|----------------|-------|
| Sandbox execution | `services/sandbox/python_runner.py`, `services/sandbox/shell_runner.py` | Used by `run_python` / `shell` in `layla/tools/registry.py`; config timeouts + optional shell allowlist; `sandbox_python_memory_limit_mb` (RLIMIT_AS on POSIX); isolated temp dir per `run_python` |
| Tool reliability | `services/tool_args.py` | Validates `args` for selected tools when `tool_args_validation_enabled` |
| Code search | `services/code_intelligence.py`, tool `search_codebase` | Workspace graph + semantic `search_workspace`; sandbox-scoped `root` |
| Routing (large context) | `services/model_router.py` | `coding_model_large_context`, `coding_large_context_threshold` vs `context_len` from `llm_gateway` |
| Retrieval weights / BGE | `layla/memory/vector_store.py`, `services/retrieval.py` | Weighted RRF; `coding_boost` from deep reasoning; optional BGE CrossEncoder in `rerank()`; fused context: `max_chars_per_source`, `retrieval_line_overlap_threshold` |
| Knowledge ingestion | `services/doc_ingestion.py`, `main.py` routes, UI Knowledge panel | Writes under `knowledge/_ingested/`; `knowledge_ingestion_enabled`; content-hash dedup (`.hash` sidecars); `doc_injection_guard_enabled` (framing + redaction) |
| Learning gate | `layla/memory/distill.py`, `layla/memory/db.py` `save_learning` | `learning_quality_gate_enabled`, `learning_quality_min_score` |
| Multi-agent (prompt) | `services/agent_roles.py`, `agent_loop._build_system_head` | `multi_agent_orchestration_enabled` + deep mode |
| Fast chat UX | `routers/agent.py`, `agent_loop.py`, `services/response_cache.py` | Trivial greeting fast-path, instant stream `thinking` event, optional response cache (`response_cache_*`) |
| Productization | `version.py`, `services/auto_updater.py`, `main.py`, `ui/index.html` | `GET /version`, `GET /update/check`, `POST /update/apply` (allow_run + approval), UI health panel version/update controls |
| Learning score floor | `layla/memory/db.py`, `agent_loop._load_learnings` | `learnings.score` column + prompt-time filter by `learning_min_score` |

Tests: `tests/test_sandbox_runners.py`, `tests/test_code_intelligence.py`, `tests/test_tool_args.py`, `tests/test_tool_output_validator.py`.

---

## Prebuilt capability domains

Maps each capability domain to implemented modules and missing components. See [LAYLA_PREBUILT_PLATFORM.md](LAYLA_PREBUILT_PLATFORM.md) for full architecture.

| Domain | Implemented Modules | Missing Components |
|--------|---------------------|--------------------|
| Conversation Intelligence | `orchestrator.py`, `context_manager.py`, `stt.py`, `tts.py`, `llm_gateway.py`, `inference_router.py`, `token_count.py`, `db.conversation_summaries`, `db.relationship_memory`, `style_profile.py` | Companion intelligence — done; voice mode detection, streaming STT, configurable TTS — done |
| Knowledge Intelligence | `vector_store.py`, `db.py`, `retrieval.py`, `graph_reasoning.py`, `distill.py`, `workspace_index.py` | graph_reasoning (spaCy + networkx) — done; faiss-cpu, qdrant |
| Code Intelligence | `file_understanding.py`, `workspace_index.py` (tree-sitter), `registry` (python_ast, grep_code, etc.) | tree-sitter: functions, classes, imports, calls — done |
| Automation | `browser.py` (optional persistent profiles), `task_graph.py`, `planner.py`, `research_stages.py`, registry (shell, `shell_session_*`, run_python, schedule_*, crawl_site), `http_response_cache.py` | crawl4ai, docker SDK, pyperclip |
| Chat Transports | `discord_bot/`, `transports/slack_bot.py`, `transports/telegram_bot.py`, `transports/base.py` (allowlist + `/pair`, `runtime_safety` keys `transport_*`) | Matrix, WhatsApp (optional); OpenClaw gateway sidecar — `docs/OPENCLAW_BRIDGE.md` |
| Model Management | `llm_gateway.py`, `inference_router.py`, `model_manager.py`, `model_recommender.py`, `model_benchmark.py`, `model_router.py` | inference_router: llama_cpp, openai_compatible (vLLM), ollama — done; model A/B comparison |
| Agent Runtime | `agent_loop.py` (+ `tool_policy.py`, `tool_loop_detection.py`), `task_graph.py`, `shared_state.py`, `decision_schema.py`, `mission_manager.py`, `routers/*.py` | Parallel agent roles (run_parallel_ready) — done; OpenTelemetry |
| Skill Library | `layla/skills/registry.py`, `markdown_skills.py`, `skills/` (optional `SKILL.md`), `plugin_loader.py`, `planner.py` | DAG composition, skill metrics |
| Hardware Intelligence | `hardware_detect.py`, `first_run.py`, `agent/install/` (hardware_probe, model_selector, model_downloader, installer_cli), `runtime_safety._probe_hardware`, `runtime_safety.resolve_model_path` | First-run installer: detect hardware, recommend from catalog, download to ~/.layla/models, generate config. Metal refinement, disk benchmark, thermal (psutil) |
| Self Improvement | `study_service.py`, `self_improvement.py`, `capability_discovery.py`, `integration_sandbox.py`, `benchmark_suite.py`, `sandbox_validator.py`, `distill.py`, `performance_monitor.py`, `system_optimizer.py`, `capabilities/registry.py` | Capability evolution pipeline — done; runtime optimization — done; RL feedback loop |
| User Interface | `ui/index.html`, `tui.py`, `cursor-layla-mcp/server.py`, `layla.py` | Platform control center — Health, Models, Knowledge, Plugins panels; GET /platform/* APIs |

---

## Capability evolution pipeline

| Step | Module | Description |
|------|--------|-------------|
| Discover | `capability_discovery.py` | `discover_candidate_libraries`, `fetch_pypi_candidates`, `fetch_github_candidates` |
| Sandbox | `integration_sandbox.py` | Temp venv, install, compatibility tests, benchmarks |
| Benchmark | `benchmark_suite.py` | vector_search, embedding, reranker, web_scraper; stores in `capability_implementations` |
| Promote | `capabilities/registry.py` | Priority: config override → best benchmark → default |

---

## Capability routing and performance modes (2026-03)

| Component | Module | Description |
|-----------|--------|-------------|
| Task model routing | `agent_loop._autonomous_run_impl`, `model_router.py`, `llm_gateway._get_llm` | When routing enabled: `classify_task(goal, context)` → per-task GGUF (`coding_model` / `reasoning_model` / `chat_model` or `models{}` block). `select_model()` + `llm_model_coding` capability for Magicoder vs default; benchmarks via `capability_implementations`. |
| `llm_model_coding` | `capabilities/registry.py` | `magicoder` + `default_coding` impls (`llama_cpp` module_path). |
| Performance modes | `system_optimizer.get_effective_config()` | `performance_mode`: `low` / `mid` / `high` / `auto` (explicit `auto` only → hardware tiers; omitted = `mid`). Runtime overrides: `n_ctx`, tool limits, `retrieval_cross_encoder_limit`, `max_plan_depth`, `enable_cognitive_workspace`, `planning_enabled`. |
| Plugin capabilities | `plugin_loader.py` | YAML `capabilities:` → `register_implementation`. |
| Startup capability benchmarks | `main.py` lifespan | If `benchmark_on_load`: daemon thread runs `benchmark_suite.run_benchmark` for embedding + vector_search. |
| Output polish | `services/output_polish.py`, `routers/agent.py` | `polish_output` on finished replies and SSE final content. |
| UI | `ui/index.html` | Regenerate (retry), Stop (AbortController on `/agent`). |

---

## Architecture optimization (2025-03)

| Component | Module | Description |
|-----------|--------|-------------|
| Token budgeting | `context_budget.py` | Per-section limits (identity 400, memory 800, knowledge 800, graph 200, workspace 400). Integrates with context_manager. |
| Two-stage retrieval | `vector_store.py` | vector+BM25→top 20, light rerank→top 10, cross-encoder→top 5. Config `retrieval_cross_encoder_limit`. |
| Graph expansion cache | `graph_cache.py` | TTL 300s cache for expand_query_via_graph. Key: hash(query). |
| Workspace dependency graph | `workspace_index.py` | build_workspace_graph(), get_workspace_dependency_context(). Nodes: files, functions, classes, imports. Edges: calls, imports, inherits. |
| agent_loop modularization | `decision_engine.py`, `failure_recovery.py`, `tool_orchestrator.py`, `context_builder.py` | Extracted logic; autonomous_run remains orchestrator. |
| Runtime performance | `system_optimizer.py` | Tracks agent_decision_ms. get_summary() exposes performance (mean, p95, count) for /health, /doctor. |
| Adaptive parallelism | `task_graph.py` | GraphExecutor._adaptive_workers() adjusts workers by CPU/RAM (psutil). |

## Runtime optimization system

| Component | Module | Description |
|-----------|--------|-------------|
| Metrics | `system_optimizer.py` | CPU, RAM, GPU, token throughput, tool latency, retrieval latency, agent_decision_ms |
| Adaptive config | `system_optimizer.py` | `get_effective_config()` — runtime overrides for n_ctx, max_tool_calls, semantic_k, etc. Never persists. |
| Observability | `observability.py` | `log_agent_decision`, `log_tool_result`, `log_retrieval_cache_*` — structured logging + performance_monitor |
| Health/doctor | `main.py`, `system_doctor.py` | `system_optimizer` summary in GET /health and GET /doctor |

---

## Platform UI components

| Panel | API | Description |
|-------|-----|-------------|
| Health | GET /health, GET /health?deep=true | Fast default health status; optional deep vector probe on demand |
| Models | GET /platform/models | Active model, installed .gguf list, catalog (jinx/dolphin/hermes/qwen), benchmarks |
| Knowledge | GET /platform/knowledge | Summaries, learnings, graph nodes, timeline, user identity |
| Plugins | GET /platform/plugins | Loaded plugins, skills, tools |
| Projects | GET /platform/projects | Project context: goals, progress, blockers, last_discussed |
| Timeline | (via /platform/knowledge) | Timeline events (conversation summaries, milestones) |
| Mission tracker | Research panel | /missions, /mission/{id} |

---

## Bug fixes (2026-03-19)

| Area | Fix | Files |
|------|-----|-------|
| Mission API parsing | `/mission` now reads `workspace_root`, `allow_write`, and `allow_run` from parsed body dict | `agent/main.py` |
| Health endpoint cost | `GET /health` now uses lightweight learning count; Chroma probe runs only on `?deep=true` | `agent/main.py`, `agent/layla/memory/db.py` |
| Plugins endpoint cost | `/platform/plugins` now uses 60s TTL cache to avoid repeated plugin scans | `agent/main.py` |
| Updater safety | `apply_update()` now checks dirty tree, syncs dependencies, returns `restart_required` | `agent/services/auto_updater.py` |
| Approval robustness | `/approve` is idempotent for already executed approvals; unknown tools return structured errors | `agent/routers/approvals.py` |
| Download integrity | Optional SHA-256 verification added to `verify_file()` | `agent/install/model_downloader.py` |

---

## Companion intelligence subsystem

| Component | Module | Description |
|-----------|--------|-------------|
| Relationship memory | `db.py` | `relationship_memory` table; add_relationship_memory, get_recent_relationship_memories; populated on conversation compress |
| Timeline events | `db.py` | `timeline_events` table; add_timeline_event, get_recent_timeline_events; populated on conversation compress; event_type: life_event, project_milestone, goal, blocker, conversation_summary |
| User identity | `db.py` | `user_identity` table; get_user_identity, set_user_identity, get_all_user_identity; keys: verbosity, humor_tolerance, formality, response_length, life_narrative_summary; tools: get_user_identity, update_user_identity |
| Episodes | `db.py` | `episodes`, `episode_events` tables; create_episode, add_episode_event; grouped timeline/summaries/reflections |
| Tool outcomes | `db.py` | `tool_outcomes` table; record_tool_outcome, get_tool_reliability; planner uses reliability hints |
| Goals | `db.py` | `goals`, `goal_progress` tables; add_goal, add_goal_progress, get_active_goals; tools: add_goal, add_goal_progress, get_active_goals |
| Reflection engine | `reflection_engine.py` | generate_reflections after task; what worked/failed/improve; store as learnings; integrated with _save_outcome_memory |
| Knowledge distiller | `knowledge_distiller.py` | distill_learnings_to_insights; periodic compression; scheduler job every 60 min |
| Curiosity engine | `curiosity_engine.py` | identify_knowledge_gaps, get_curiosity_suggestions |
| Experience replay | `experience_replay.py` | run_experience_replay; review tool outcomes and reflections |
| Personal knowledge graph | `personal_knowledge_graph.py` | get_personal_graph_context; unified timeline, projects, goals, identity |
| Reasoning strategies | `reasoning_strategies.py` | get_strategy_for_task, get_strategy_prompt_hint; multi-strategy hints for complex goals |
| Style profile | `style_profile.py` | Tone, response_style, topics; embeddings + clustering; update_profile_from_interactions |
| Voice | `stt.py`, `tts.py` | detect_voice_mode, transcribe_streaming; get_voice_options, tts_voice config |
| Context injection | `agent_loop._build_system_head` | Relationship memory, timeline events, user identity, conversation summaries, style profile, personal graph, reasoning strategies, active goals |

---

## Intelligence systems (model-agnostic)

| System | Module | Description |
|--------|--------|-------------|
| Reflection engine | `services/reflection_engine.py` | Post-task reflections (what worked/failed/improve) → learnings |
| Episodic memory | `db.episodes`, `db.episode_events` | Group timeline, summaries, reflections into episodes |
| Knowledge distiller | `services/knowledge_distiller.py` | Compress learnings → higher-level insights; scheduler 60 min |
| Tool outcome learning | `db.tool_outcomes` | Record success/latency; planner prefers reliable tools |
| Workspace semantic graph | `workspace_index.py` | Edges: calls, depends_on, implements |
| Goal engine | `db.goals`, `db.goal_progress` | Long-term goals; integrated with project context |
| Curiosity engine | `services/curiosity_engine.py` | Identify knowledge gaps; suggest learning |
| Multi-strategy reasoning | `services/reasoning_strategies.py` | Strategy hints (decomposition, analogy, etc.) for complex goals |
| **Cognitive workspace** | `services/cognitive_workspace.py` | Tree-of-thought: generate approaches (search/reasoning/tools) → evaluate → choose best; inject strategy_hint into decision prompt and plan context |
| Experience replay | `services/experience_replay.py` | Review outcomes/reflections for planning heuristics |
| Personal knowledge graph | `services/personal_knowledge_graph.py` | Unified graph for retrieval (timeline, projects, goals, identity) |

---

## Debug & upgrade analysis

See [docs/DEBUG_AND_UPGRADE_ANALYSIS.md](DEBUG_AND_UPGRADE_ANALYSIS.md) for:
- Test flakiness fix (system_overloaded in pre_read_probe tests)
- OSS upgrade opportunities (instructor, tiktoken, vLLM/Ollama)
- Deprecation warnings (torch.quantization, ChromaDB Pydantic)

---

## Phase 2 hardening (verified)

| Area | Code |
|------|------|
| SSE / `stream_reason` task model | `agent_loop.stream_reason` + `_stream_reason_body`; `routers/agent.py` passes `model_override` |
| Missing routed GGUF | `services/llm_gateway.py` `_get_llm` falls back to `model_filename` |
| Polish safety for code/JSON | `services/output_polish.py` `_looks_like_code_or_structured` |
| `performance_mode` auto | `services/system_optimizer.py` — VRAM/RAM numeric thresholds via `detect_hardware()` |
| Setup overlay + status | `ui/index.html` `showSetupOverlay` enabled; `GET /setup_status` includes `performance_mode`; badge via `refreshModelStatus` |
| Retrieval cap | `services/retrieval.py` `MAX_K = 5` on `build_retrieved_context` |
| Tests | `tests/test_capability_routing.py` — `test_routing_consistency`, `test_missing_model_graceful_fallback` |

---

## How to verify

1. **Run tests**: `cd agent && python -m pytest tests/ -v`
2. **Wakeup**: `python layla.py wakeup` — Echo greets, study plans listed.
3. **Project context**: Set via API or DB; check agent context includes project + lifecycle.
4. **File understanding**: Call `analyze_file(path)` for .dxf, .py, .md, .json, .ipynb and binary extensions; expect format + intent.
5. **Approval**: Trigger a write from Layla; confirm approval_required; approve and confirm apply.
