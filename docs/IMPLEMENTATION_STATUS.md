# Implementation Status vs LAYLA_NORTH_STAR.md

This document maps each section of the North Star to code, tests, and verification so we never stray from the plan.

**Production contract (caps, safety, `/health`, logging):** [PRODUCTION_CONTRACT.md](PRODUCTION_CONTRACT.md) — maps operational guarantees to config and tests.

**Layout (2026 consolidation):** SQLite schema in **`agent/layla/memory/migrations.py`**; table APIs in domain modules re-exported from **`db.py`**. Agent HTTP: **`routers/agent.py`** composes **`learn.py`** + **`agent_tasks.py`**; background workers in **`services/agent_task_runner.py`**. Tiered prompt caps: **`services/prompt_tier_budget.py`**.

---

| § | North Star | Implementation | Tests / verification |
|---|------------|----------------|----------------------|
| 1 | Core purpose: partner system, grow with user, assist, structure, translate, improve, maintain identity | Identity in `.cursor/rules/layla-assistant.mdc`, `agent_loop.py` system head, learnings + style profile | E2E and agent loop tests |
| 2 | User reality: programming, fabrication, geometry, automation, docs, research, planning; focus on friction points | Morrigan prompt (planning, docs, Python, DXF→fabrication); fabrication domains + study plans | Study plans seeded; capabilities test |
| 3 | Project participation: project awareness, lifecycle (Idea→Planning→Prototype→Iteration→Execution→Reflection) | `project_context` table: project_name, domains, key_files, goals, **lifecycle_stage**, **progress**, **blockers**, **last_discussed**; `get_project_context` / `set_project_context`; injected in agent head; **GET/POST /project_context**, **GET /platform/projects** API | `test_north_star.py::test_project_context_lifecycle`, `test_platform_ui.py::test_platform_projects` |
| 4 | File ecosystem: geometry, fabrication, programming, documentation, visual — interpret intent | `agent/layla/file_understanding.py`: all North Star extensions; `analyze_file()`, `get_supported_extensions()`; **`agent/layla/geometry/`** — structured CAD-like programs (`geometry_validate_program`, `geometry_execute_program`); **`geometry_extract_machining_ir`** | `test_north_star.py::test_file_understanding_*`; `test_geometry_schema.py`, `test_geometry_executor.py`, **`test_geometry_bridge_security.py`**, **`test_machining_ir.py`**; [GEOMETRY_MODULE_SECOND_SWEEP.md](GEOMETRY_MODULE_SECOND_SWEEP.md) |
| 5 | Workflow translation: Geometry→Fabrication→Machine intent; DXF→machinable, parametric→geometry, Python→automation | **PARTIAL:** deterministic **`layla.geometry.machining_ir`** (features → order → `machine_steps_preview`) + tool **`geometry_extract_machining_ir`** (adds `machine_readiness` + `ir_validation`); `generate_gcode` (2D polyline) + `gcode_validation`; tool **`validate_fabrication_bundle`**; **not** full CAM/feeds/simulation — see **[FABRICATION_IR_AND_TOOLCHAIN.md](FABRICATION_IR_AND_TOOLCHAIN.md)** | `test_machining_ir.py`; `test_decision_policy.py` (IR/G-code structural checks); geometry + fabrication domains |
| 6 | Execution loop: Learn→Plan→Assist→Evaluate→Improve; applied learning | **PARTIAL + improving:** study service, planner, tools; **`services/outcome_evaluation.evaluate_outcome`** + injection into **`reflection_engine`** / **`services/outcome_writer._save_outcome_memory`**; capability `record_practice` | `test_outcome_evaluation.py`; `test_study_integration`, scheduler |
| 7 | Learning judgment: usefulness, transferability, real-world impact; selective learning | `usefulness_score` / `learning_quality_score` on capability_events; `learning_min_score` on **`get_recent_learnings`**; **`memory_retrieval_min_adjusted_confidence`** filters **`_semantic_recall`** (0 = off) | `record_practice`; retrieval filter in agent loop |
| 8 | Failure awareness: workflow breakdowns, planning gaps, execution issues; assist recovery | **`recovery_strategy`:** `replan` \| `retry_constrained` \| `escalate_user` on `recovery_hint`; prompt **Next step** line in `format_recovery_hint_for_prompt`; replan nudge in `_llm_decision` when strategy `replan` and `should_plan` false; verification + `classify_failure_and_recovery` | `test_failure_classify_*`, `test_format_recovery_hint_for_prompt` |
| 9 | Documentation intelligence: technical→human translation; core strength | Writing domain, style profile, Morrigan “documentation” priority; study plans for writing | Study plans; style_profile in head |
| 10 | Initiative model: suggest improvements, propose projects, explore safely; gated | **PARTIAL:** Wakeup initiative (`wakeup_include_initiative`, `INITIATIVE_RULES`). **Optional:** `inline_initiative_enabled` — one heuristic line after multi-tool replies (`services/initiative_inline.py`) | test_wakeup_initiative_suggestion; manual inline initiative |
| 11 | Personality: Morrigan, Nyx, Echo, Eris, Lilith; Lilith governs autonomy | `personalities/*.json`; orchestrator; deliberation roster; **`orchestrator.decision_bias_prompt_extension`** maps `decision_bias` → concrete tool nudges in `_llm_decision` | Aspect selection tests |
| 12 | Decision system: feasibility, knowledge depth, alignment, creativity, risk; execution via Morrigan | `orchestrator.build_deliberation_prompt` with structured roles; CONCLUSION — MORRIGAN; bias extension augments JSON decision path | Deliberation prompt format |
| 13 | Identity continuity: evolve, consistency, quirks; Echo tracks long-term growth | Echo prompt; style_profile; learnings; aspect_memories; `human_aligned` bias nudge in decisions | Wakeup; Echo in deliberation |
| 14 | Autonomy: suggest, guide, organize; eventually initiate safely | **PARTIAL:** Wakeup + optional inline suggestion (§10); no mid-task optimization engine; approval flow; study scheduler | Wakeup; approval for write/run |
| 15 | Safety: Lilith gates file modification, autonomous execution, learning acceptance | Lilith systemPromptAddition; approval flow; usefulness gating for reinforcement | Refusal tests; approval API |
| 16 | Local-first: persistent, local; remote opt-in | **Implemented:** Config `remote_enabled`, `remote_api_key`, `remote_allow_endpoints`, `remote_mode` (observe \| interactive). Auth middleware: Bearer token for non-localhost; endpoint allowlist. Bind to localhost only unless `remote_enabled` (see docs/REMOTE_ARCHITECTURE.md). No autonomy added. | tests/test_remote.py |
| 17 | Toolchain awareness: format transitions, workflow dependencies, automation paths | **PARTIAL:** file_understanding + project context + **[FABRICATION_IR_AND_TOOLCHAIN.md](FABRICATION_IR_AND_TOOLCHAIN.md)** explicit DXF→IR→G-code chain; no full dependency-cost graph | In-head context + IR doc |
| 18 | Project discovery: detect opportunities, synthesize, evaluate feasibility | **PARTIAL:** `run_project_discovery()` (LLM) + `discover_project()` (filesystem); **`project_discovery_auto_inject`** injects deterministic scan brief when `.layla/project_memory.json` sparse (`services/project_discovery_hooks.py`, `_build_system_head`) | test_project_discovery_*; **`test_project_discovery_hooks.py`** |
| 19 | Long-term growth: capability, alignment, partnership | Capabilities + domains; learnings; study plans; usefulness-weighted growth | Capability events; seed plans |
| 20 | Ultimate goal: collaborative intelligence that grows, improves work, expands possibility | Whole system; North Star as single source of truth | Full E2E and integration tests |

### Fabrication assist (scaffold, non–agent-loop)

| Item | Role | Code / docs | Tests |
|------|------|-------------|--------|
| Fabrication assist boundary | Layla guides / explains; operator plugs a deterministic kernel via **`BuildRunner`**; subprocess **`echo_kernel`** + Pydantic schemas | `fabrication_assist/assist/` (`schemas`, `errors`, `echo_kernel`, `session`, `variants`, `explain`, `runner`, `layla_lite`); [FABRICATION_ASSIST.md](FABRICATION_ASSIST.md); `fabrication_assist/README.md`; [knowledge/fabrication-assist-layer.md](../knowledge/fabrication-assist-layer.md) | `test_fabrication_assist*.py` (core, runner, CLI, session edges, doc links) |

**Note:** On `main`, `StubRunner` only; do not import `fabrication_assist` from `agent/main.py` or `agent_loop.py` unless deliberately integrating.

---

## Operator UX (roadmap-aligned)

| Item | Where | Notes |
|------|--------|--------|
| Context bar, compact, session stats, Skills tab, prompt ↑ | `agent/ui/index.html`; `POST /compact`, `GET /ctx_viz`, `GET /session/stats`, `GET /history`, `GET /skills`; SSE context hints in `agent_loop` | [PARITY_AUDIT.md](PARITY_AUDIT.md) |
| Runtime limits + potato preset | `agent/config_schema.py`, `main.py` `/settings/preset`, Web UI Settings | `docs/POTATO_MODE.md` |
| Study presets / workspace suggestions | `routers/study.py` `/study_plans/presets`, `/suggestions`, `/derive_topic`; Web UI Study panel | Local-only signals from `sandbox_root` |
| Persona focus (dual voice depth) | `POST /agent` `persona_focus`, `agent_loop._build_system_head`, MCP `chat_with_layla` | Primary `aspect_id` unchanged |
| Remember + learning tags | Web UI, `POST /learn/` `tags`, `db.py` `learnings.tags` | Discord `/note` uses `save_learning_async` |
| Multi-chat rail, `/conversations*`, session checkpoint | `agent/ui/` + `main.py`; `GET /session/export` (messages + pending + history tail); `GET /values.md` | Web UI Help; `test_session_export.py` |
| Projects (presets) | `layla_projects` table; `GET/POST/PATCH/DELETE /projects`; optional `project_id` on `POST /agent` | `test_projects_api.py` |
| Installer maintenance | `agent/install/installer_cli.py` — `doctor`, `repair`, `packs`, `download <url>`; `agent/install/packs/*.json` | `test_install.py` |
| Starter knowledge pack | `knowledge/starter/` (how-to, tools, safety) | Indexed with other knowledge; see pack `README.md` |
| Audit rubric | `docs/AUDIT_RUBRIC.md` | Manual sign-off |
| Onboarding assets (pointers only) | `docs/ONBOARDING_ASSETS.md` | No bundled third-party zips |
| Relationship codex (UI + API) | `GET/PUT /codex/relationship?workspace_root=` ([`agent/routers/codex.py`](../agent/routers/codex.py)); Library → Workspace → **Codex**; tool **`codex_suggest_update`** (read-only hints) | Optional inject: `relationship_codex_inject_enabled` + `relationship_codex_inject_max_chars`; digest **after identity** in `_build_system_head`; **`decision_bias_prompt_extension`** + inline initiative when codex has entities |
| Product UX evaluation doc | [`docs/PRODUCT_UX_ROADMAP_VS_CURRENT.md`](PRODUCT_UX_ROADMAP_VS_CURRENT.md) | Maps legacy “Life OS” draft vs shipped features + deferred tiers |
| Project memory + long-horizon background | `services/project_memory.py` (schema v2: `modules`, `issues`, `plans`); `POST /agent` `understand_mode` + optional `plan_mode` persist; tools `scan_repo` / `update_project_memory`; background `continuous` + caps; optional **`plan_id`** on background enqueue | `test_project_memory.py`; recommend `.layla/` in project `.gitignore` |
| Planning-first (SQLite plans + API) | `layla_plans` in `layla/memory/db.py`; `routers/plans.py` (`GET/POST /plans`, approve, execute); `plan_id` + `plan_steps` on `plan_mode` response; `planning_strict_mode` + `plan_approved` / `active_plan_id` in `agent_loop` / `planner.execute_plan` / `background_job_worker` | `test_plans_api.py`, `test_planning_strict_mode.py` |
| Discord D1–D5 | `discord_bot/README.md`, `/note`, existing `/ask` + summon/TTS/music | Explicit notes only for codex-style memory |

### Structured engineering partner (optional pipeline)

| Item | Where | Notes |
|------|--------|------|
| Spec + contracts | `docs/STRUCTURED_ENGINEERING_PARTNER.md`, `LAYLA_NORTH_STAR.md` §21 | Modes, clarifier block, critics, refiner, validator |
| Orchestration | `agent/services/engineering_pipeline.py` | `run_plan_light`, `run_execute_pipeline`, planning ContextVar lock |
| Agent loop + legacy `should_plan` guard | `agent/agent_loop.py` | Execute path + `engineering_planning_locked()` |
| HTTP + precedence vs `plan_mode` | `agent/routers/agent.py` | Fast-path/cache bypass for plan/execute modes; `clarification_reply` |
| Planner kwargs | `agent/services/planner.py` | `skip_engineering_pipeline` forwarded to nested `autonomous_run` |
| MCP | `cursor-layla-mcp/server.py` | `engineering_pipeline_mode`, `clarification_reply`; surfaces `pipeline_needs_input` |
| UI | `agent/ui/index.html`, `agent/ui/js/layla-app.js` | Eng. pipeline mode select; clarification panel |
| Tests | `agent/tests/test_engineering_pipeline.py`, `test_in_loop_plan_governance.py` | Lock + clarifier block + kwargs; governance forces `engineering_pipeline_enabled` false |

### Deferred (roadmap only; not in this release scope)

- **CAD / GENCAD swarms** — keep as optional tools/plugins; no new orchestration stack (see `docs/ROADMAP.md` / `docs/MILESTONES.md` if present).
- **Memory-driven personalities** — design-only **FUTURE**; no dedicated DB or personality rewrite in this track. **Relationship codex:** [`agent/services/relationship_codex.py`](../agent/services/relationship_codex.py) + **HTTP + Web UI** + **decision/initiative wiring** + **`codex_suggest_update`** (no auto-write). **Optional** digest when `relationship_codex_inject_enabled` is true (default off). See [`docs/PRODUCT_UX_ROADMAP_VS_CURRENT.md`](PRODUCT_UX_ROADMAP_VS_CURRENT.md).

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
- **Non-clinical psychology boundary** ([`docs/ETHICAL_AI_PRINCIPLES.md`](ETHICAL_AI_PRINCIPLES.md) §11): no diagnostic claims or DSM/ICD labels for the operator; `direct_feedback_enabled` + `pin_psychology_framework_excerpt` in config/UI; reflective-message RAG widen in `agent_loop._needs_knowledge_rag`; Echo/Lilith pinned framework excerpt; `style_profile` key `collaboration` via `services/style_profile.py`; RUNBOOKS operator-local psychology files; optional sources/libraries catalog [`docs/OPERATOR_PSYCHOLOGY_SOURCES.md`](OPERATOR_PSYCHOLOGY_SOURCES.md).

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
| Task budget / adaptive envelope | `services/task_budget.py`, `agent_loop.py` | When `task_budget_enabled`: run-level caps for tools + plan depth + retrieval; `macro_planning_allowed`; `pipeline_variant`; `run_budget_summary` + `log_run_budget_summary`; optional Langfuse hook in `services/langfuse_export.py` |
| Telemetry | `services/telemetry.py`, `db.telemetry_events`, `db.log_telemetry_event` / `get_recent_telemetry_events` | `telemetry_enabled` (default true); `telemetry_log_trivial` to log `reasoning_mode=none` runs; `suggest_optimization()` heuristic over last 50 events |
| Agent loop safety / hygiene | `services/tool_output_validator.py`, `agent_loop.py`, `services/tool_loop_detection.py`, `decision_schema.py` | Tool output normalization; per-run exact duplicate suppression; `push_and_evaluate(..., reasoning_mode=)` tightens default repeat stop in `none`/`light`; `action: "none"`; `max_patch_lines` before `apply_patch` |
| UI | `agent/ui/index.html` | `#reasoning-mode-badge` |

Tests: `tests/test_reasoning_classifier.py`, `tests/test_task_budget.py`.

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
| Fast chat UX | `routers/agent.py`, `agent_loop.py`, `services/response_cache.py` | Trivial greeting fast-path, instant stream `thinking` event, optional response cache (`response_cache_*`); **`POST /agent` response variants** documented in `docs/POST_AGENT_RESPONSE_CONTRACT.md` (`state.status`, normalized `state.steps`) |
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
| Agent Runtime | `agent_loop.py` (+ `tool_policy.py`, `tool_loop_detection.py`, **`services/decision_policy.py`** PolicyCaps clamp per tick), `task_graph.py`, `shared_state.py` (blackboard, decision trace), `decision_schema.py`, `mission_manager.py`, `routers/*.py` | Parallel agent roles (run_parallel_ready) — done; OpenTelemetry; GET **`/agent/decision_trace`**, **`/agents/blackboard/{job_id}`** |
| Skill Library | `layla/skills/registry.py`, `markdown_skills.py`, `skills/` (optional `SKILL.md`), `plugin_loader.py`, `planner.py` | DAG composition, skill metrics |
| Hardware Intelligence | `hardware_detect.py`, `first_run.py`, `agent/install/` (hardware_probe, model_selector, model_downloader, installer_cli), `runtime_safety._probe_hardware`, `runtime_safety.resolve_model_path` | First-run installer: detect hardware, recommend from catalog, download to ~/.layla/models, generate config. Metal refinement, disk benchmark, thermal (psutil) |
| Self Improvement | `study_service.py`, `self_improvement.py`, `capability_discovery.py`, `integration_sandbox.py`, `benchmark_suite.py`, `sandbox_validator.py`, `distill.py`, `performance_monitor.py`, `system_optimizer.py`, `capabilities/registry.py` | Capability evolution pipeline — done; runtime optimization — done; RL feedback loop |
| User Interface | `ui/index.html`, `tui.py`, `cursor-layla-mcp/server.py`, `layla.py` | Web `/ui`: left Options → Content policy (`/settings`); tiered right column (Status, Workspace, Safety, Research, Help); Layla + facet chip; stream typing dots; GET /platform/* APIs |

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
| Task model routing | `agent_loop._autonomous_run_impl`, `model_router.py`, `llm_gateway._get_llm` | When routing enabled: `classify_task_for_routing(goal, context, cfg)` → per-task GGUF (`coding_model` / `reasoning_model` / `chat_model` or `models{}` block). Dual GGUF when `should_use_dual_models()` + `resolve_dual_model_basenames()` (`chat_model_path` / `agent_model_path` or basenames); `force_dual_models` bypasses RAM gate; optional `route_default_to_chat_model`. `select_model()` + `llm_model_coding` + benchmarks. `/health` + `/platform/models` → `model_routing`. |
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
| agent_loop modularization | `services/outcome_writer.py` (+ `decision_engine.py`, `failure_recovery.py`, …) | **`outcome_writer`**: outcome memory, Echo memories, patch extract, auto-learnings; streaming/system-head remain in `agent_loop` for now. |
| Runtime performance | `system_optimizer.py` | Tracks agent_decision_ms. get_summary() exposes performance (mean, p95, count) for /health, /doctor. |
| Adaptive parallelism | `task_graph.py` | GraphExecutor._adaptive_workers() adjusts workers by CPU/RAM (psutil). |

## Runtime optimization system

| Component | Module | Description |
|-----------|--------|-------------|
| Metrics | `system_optimizer.py` | CPU, RAM, GPU, token throughput, tool latency, retrieval latency, agent_decision_ms |
| Adaptive config | `system_optimizer.py` | `get_effective_config()` — runtime overrides for n_ctx, max_tool_calls, semantic_k, etc. Never persists. |
| Observability | `observability.py` | `log_agent_decision`, `log_tool_result`, `log_retrieval_cache_*` — structured logging + performance_monitor |
| Health/doctor | `main.py`, `system_doctor.py`, `services/health_snapshot.py` | `system_optimizer` summary; sanitized config snapshot + dependency matrix on GET /health; GET /doctor unchanged |

---

## Platform UI components

| Panel | API | Description |
|-------|-----|-------------|
| Health | GET /health, GET /health?deep=true, GET /health/deps | `active_model`, `effective_config`, `features_enabled`, `dependencies`; Chroma vector probe on `?deep=true`; minimal deps on `/health/deps`. UI: unified poller. See `docs/GOLDEN_FLOW.md` |
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
| Reflection engine | `reflection_engine.py` | generate_reflections after task; what worked/failed/improve; store as learnings; integrated with **`outcome_writer._save_outcome_memory`** |
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

1. **Run tests**: `cd agent && python -m pytest tests/ -v -m "not slow and not e2e_ui"` (default CI slice). Optional UI e2e: `pip install -r requirements-e2e.txt`, `python -m playwright install chromium`, then `pytest tests/e2e_ui/ -m e2e_ui`. **Lint**: `ruff check agent fabrication_assist` (full rules from `pyproject.toml`, including import order **I**).
2. **Wakeup**: `python layla.py wakeup` — Echo greets, study plans listed.
3. **Project context**: Set via API or DB; check agent context includes project + lifecycle.
4. **File understanding**: Call `analyze_file(path)` for .dxf, .py, .md, .json, .ipynb and binary extensions; expect format + intent.
5. **Approval**: Trigger a write from Layla; confirm approval_required; approve and confirm apply.
