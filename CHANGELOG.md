# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## Unreleased

### Documentation & GitHub presence

- Professional root **README**: centered hero, CI badge, screenshots (`readme-assets/`), table of contents, quality-enforcement callout, clone URLs, doc hub link.
- Expanded **docs/README.md** (documentation index) and **docs/media/README.md** (how to record demo GIFs/screenshots).
- **docs/GETTING_STARTED.md**: quality enforcement keys; link to media guide.
- **CONTRIBUTING.md**: canonical clone URL for GitHub.

### Quality parity hardening
- **Speculative decoding (local llama.cpp):** `services/llm_gateway.py` now optionally enables prompt-lookup speculative decoding (`speculative_decoding_enabled`, `speculative_num_pred_tokens`) for faster local inference when supported.
- **Decision reliability:** decision parsing now supports fenced/multiline JSON with simple repairs; optional `decision_model` routes decision JSON generation to a dedicated structured-output GGUF; decision prompt appends few-shot JSON shapes when `decision_few_shot_enabled` is enabled.
- **Adaptive routing signals:** model outcomes are stored locally (`model_outcomes`) and `services/model_router.select_model` can soft-bias toward models with materially higher historical success rates (when enough samples exist).
- **Golden examples:** high-score runs can persist small successful patterns and inject them into the system head as bounded few-shot context (`golden_examples_enabled`).
- **Cursor MCP approvals:** `cursor-layla-mcp/server.py` now reads pending approvals from **`GET /pending`** (`agent/routers/approvals.py`) instead of a non-existent `/approvals` endpoint.
- **Higher reliability on small models:** decision prompt now includes concrete one-line JSON examples; structured decision generation remains enabled by default (`structured_generation_enabled`, `use_instructor_for_decisions`).
- **Coding quality loop enabled by default:** `auto_lint_test_fix` + `auto_lint_test_fix_run_tests` default **on** (skips trivial `reasoning_mode=none` turns).
- **Self-reflection enabled by default:** critic pass now uses configurable `self_reflection_min_length` (default 200) to avoid latency on short replies.
- **Output quality gate enabled everywhere:** agent loop now passes `cfg` into `services/output_polish.polish_output`, enabling deterministic hedge/dedupe cleanup when configured.
- **Conversation continuity:** `shared_state.get_conv_history` rehydrates from SQLite `conversation_messages` on first access after restart.
- **Deterministic quality enforcement:** deterministic tool verification + reduced tool visibility (default cap 15) + plan pre-validation + multi-dimensional validation matrix + strict completion gate + proactive context protection thresholds.

### Cohesive execution wiring
- **Single HTTP entry:** `services/coordinator.run` (resume merge, optional git worktree, `memory_consolidation.consolidate_session` after run) → `dispatch_autonomous_run`; `routers/agent.py` uses `run` instead of calling `dispatch_autonomous_run` directly.
- **In-loop task graph:** `planner.execute_plan_with_optional_graph` runs **all** non-empty in-loop plans via `run_with_plan_graph` when `coordinator_graph_execution_enabled` (default **on**); fallback to sequential `execute_plan` is explicit via `plan_execution_fallback`.
- **Resume:** `autonomous_run(..., resume_execution_state=..., coordinator_trace=...)` hydrates state; `POST /agent/persistent_tasks/{task_id}/resume` continues from SQLite `tasks` row.
- **Planning:** `coordinator_plan_threshold` + `coordinator_trace.complexity_score` can force `should_plan`; `create_plan` / `build_planning_bias_prompt` honor `preferred_strategy`.
- **Coordinator retries:** `coordinator_dispatch_max_attempts` + `coordinator_dispatch_retry_on_statuses` add optional HTTP-level retries (default attempts=1).
- **Defaults:** `coordinator_graph_execution_enabled` and `execution_trace_log_enabled` default **true**; `llm_gateway.run_completion` wrapped with `otel_export.maybe_span`; tool calls also emit optional `maybe_span("tool_call")`.
- **UI:** `layla-app.js` — immediate typing row for send, longer stall threshold, non-stream FSM errors, `retryLastMessage` respects FSM, reply facet uses server `aspect` id.
- **Decision policy (enforced):** `services/decision_policy.build_policy_caps` is now applied in `agent_loop` for both tool *selection* (prompt boundary) and tool *dispatch*; caps can require verify-before-mutate and tighten tool-call budget after failures.
- **Outcome loop (closed):** `state["outcome_evaluation"]` is set for reflection; last structured outcome evaluation is persisted to SQLite (`outcome_evaluations`) and read back on restart; outcome memory now records tool-less finished runs.
- **CAM extensions:** stronger `validate_gcode_text` (units/spindle/feed/safe G/M codes), `generate_gcode` supports DXF `ARC`/`CIRCLE`, new `cam/simulator.simulate_gcode`, and `cam_build_machine_intent` bundle tool (IR + feeds/speeds + validation + simulation). Tool count bumped to **194**.
- **Ship UX hardening:** `pyproject.toml` version aligned to 1.2.0; CLI `layla ask --voice` fixed; installers fail-fast on setup errors; `.gitignore` tightened for caches/governance/models.

### Architecture overhaul (target state)
- **Coordinator + dispatch:** `services/coordinator.py` builds richer traces (task budget envelope, `get_preferred_strategy`), persists runs via `layla/memory/tasks_db.py` + `tasks` migration, updates `shared_state` execution snapshots, optional `log_execution_trace`.
- **Execution state:** `execution_state.py` dict-compatible state; `agent_loop` pipeline stages (`PLAN`/`EXECUTE`/`VALIDATE`/`DEBUG`/`REFLECT`) + tool-first hints; `failure_recovery` sets `pipeline_stage` when enforcement is on.
- **Prompt split:** `services/prompt_builder.py` (static cache per aspect/config fingerprint) wired into `_build_system_head`; goal-ordered tool lists for decisions.
- **Background jobs:** APScheduler — reflection scan, codex nudge, `memory_consolidation`, daily low-confidence prune (`main.py`).
- **Knowledge:** `knowledge/starter/*.md` pack expansion; hybrid Chroma retrieval gains **domain** boost vs project context (`knowledge_retrieval_domain_boost`).
- **UI:** `ui/js/state.js` (chat FSM), `api.js`, `chat.js`, `sidebar.js`, `panels.js`; Status tab execution trace + tasks; header **retry**; conversation rail `data-conv-id` + scroll-into-view.
- **Advanced:** `worktree_manager.py`, `otel_export.py`, `strategy_stats.get_preferred_strategy`, config keys in `runtime_safety.py` + `runtime_config.example.json`.

## [1.3.0] — 2026-04-15

### Phased execution (Layla repo–aligned)
- **Wave 1 — Foundation:** Python **3.13+** hard-exit at **`agent/main.py`** import; **`version.py` 1.2.0**; **`CHANGELOG`** tagged section; **`docs/RELEASE_CHECKLIST.md`** release verification table; tool-count docs synced to **191**; **`install.sh`** references **`agent/install/run_first_time.py`**.
- **Wave 2 — Closed loop:** **`services/outcome_metrics.py`**, **`evaluate_outcome_structured()`**, planner **`last_evaluation`**, SQLite **`strategy_stats`**, **`layla/memory/strategy_stats.py`**, **`agent_loop`** persistence hook.
- **Wave 3 — Initiative + autonomy:** **`services/initiative_engine.py`**, **`services/autonomy_optimizer.py`** (config **`initiative_engine_enabled`**, **`autonomy_optimizer_enabled`**).
- **Wave 4 — Advanced MVP:** **`services/toolchain_graph.py`**, **`services/codex_semantic.py`**, **`layla/cam/`** rule-based helpers, voice-adjustment learnings in system head, **`docs/IMPLEMENTATION_STATUS.md`** updates.

### Accumulated changes (previously Unreleased)

- **Layla v3 ship-ready features:** operator quiz + RPG-style profile (`services/operator_quiz.py`, `/operator/*`), maturity XP/rank/phase (`services/maturity_engine.py`, `/wakeup` fields), Warframe-inspired UI theme + mastery card, conversation rail polish + tags (`/conversations/*`), research reports + citations (`services/research_report.py`), deterministic output quality gate (`output_quality_gate_enabled`), operator journal (`/journal*`), codex proposals (`/codex/proposals*`), self-improvement proposals with safe apply semantics (`/improvements/*`), and plan completion reports under `{workspace}/.layla/plan_reports/`. Tool count **191** (includes **`cam_feed_speed_hint`**).

- **Remote + settings UX (v2 continuation):** **`remote_rate_limit_per_minute`** + **`services/remote_rate_limit.py`** middleware (non-localhost when **`remote_enabled`**). Expanded **`remote_mode=interactive`** allowlist (UI, settings, knowledge, plans, tunnel, SW, etc.). Web UI: **`layla-bootstrap.js`** adds **`Authorization: Bearer`** from **`localStorage.layla_remote_api_key`** for same-origin fetches on non-localhost; remote key banner. Settings modal: **`openSettings` / `saveSettings`** build form from **`GET /settings/schema`**; optional features panel (**`GET /settings/optional_features`**, **`POST /settings/install_feature`**); WhatsApp paste → **`POST /knowledge/import_chat`**; git undo checkpoint (**`POST /settings/git_undo_checkpoint`**). Learnings: **`save_learning(..., aspect_id)`**, **`search_learnings_fts`** / **`get_recent_learnings`** aspect filter; **`POST /learn/`** + **`GET /memories`** accept aspect. **`config_schema`**: **`remote_api_key`**, **`remote_rate_limit_per_minute`**, admin keys editable. Windows: **`installer/bundle_embedded_python.ps1`** + **`LAYLA_BUNDLE_EMBEDDED_PYTHON=1`** hook in **`build_installer.ps1`**. Tests: **`test_remote_rate_limit.py`**. **`AGENTS.md`** tool count **190**.

- **Layla v2 foundations (agent core + ship UX):** Optional **`outlines`** (Python &lt;3.13) for structured decisions via **`services/structured_gen.py`** + **`structured_generation_enabled`**. Context: **`context_aggressive_compress_enabled`**, sliding history, **`tool_step_context_max_tokens`**, **`format_tool_steps_for_prompt`** truncation. **`worker_pool`** caps concurrent read-only tool batches; **`hardware_class`** / **`task_budget`** scaling; **`plan_steps_to_task_graph`**, **`Plan.all_ready_steps`**. New tool **`replace_in_file`** (domain + **`agent_loop`** + previews). **Admin mode** (`admin_mode`, **`admin_auto_checkpoint`**, **`admin_blocklist_override`**) bypasses approval via **`require_approval`** + **`git_checkpoint_layla`**. Tunnel API **`/remote/tunnel/*`** (**`services/tunnel_manager.py`**), skill packs **`/skill_packs/*`**, **`POST /setup/auto`**, **`data_importers`**, stubs **`skill_discovery`**, **`tool_generator`**. CORS via **`remote_cors_origins`**. PWA **`/sw.js`** + UI register. Personalities: style cards in **`orchestrator`**, **`icon_svg`**, Lilith **`will_refuse`**, Echo **`can_refuse`**, dynamic deliberation conclusion. Docs **`GETTING_STARTED.md`**, **`SECURITY.md`**; repo **`skill_packs/*/manifest.json`**; installer stubs **`build_macos.sh`**, **`build_appimage.sh`**. **`EXPECTED_TOOL_COUNT`** tracks live registry size (currently **191**).

- **Ship hardening / safety / transparency:** Inno Setup **`AppId`** closing brace. **`GET /setup/download`** — basename + control-char checks, destination confined under **`models_dir`**. **`release_updater.assert_zip_extract_safe`** before **`extractall`** (zip slip). **`main._audit`** writes **`.layla_gov/audit.log`** and **`layla.memory.db.log_audit`** (SQLite) so **`GET /audit`** matches approvals. Launcher: **`atexit`** + **`SIGTERM`/`SIGINT`** terminate uvicorn child; tray mode **`proc.wait()`** keeps parent alive. **`operator_protection_policy_pin_enabled`** injected in **`agent_loop._build_system_head`**. **`agent_loop`** / **`vector_store`**: replace silent **`except Exception: pass`** with **`logger.debug`/`warning`**. Docs: **`ETHICAL_AI_PRINCIPLES`** (shell paths, audit), **`ARCHITECTURE`**, **`CONFIG_REFERENCE`**, **`PROJECT_BRAIN`**. Web UI: onboarding styles in **`layla.css`**, setup **Escape**, setup failure **toast**. Tests: **`test_release_updater`** zip slip, **`test_health_endpoint`** invalid setup filename.

- **Windows ship path / first-run UX:** Web UI **`checkSetupStatus`**, model catalog + SSE download, workspace path in setup overlay, onboarding steps (`layla-app.js`). Per-user **`LAYLA_DATA_DIR`**: **`runtime_safety.CONFIG_FILE`**, **`default_models_dir()`**, **`layla.db`** via **`db_connection`**. **`services/release_updater.py`** merges GitHub Release ZIP into **`agent/`** when **`LAYLA_DATA_DIR`** is set; **`POST /update/apply`** uses it instead of git. **`launcher/layla_launcher.py`** + **`launcher/layla.spec`**; **`installer/layla.iss`** + **`installer/build_installer.ps1`**. **`first_run.py`** uses **`runtime_safety.CONFIG_FILE`** / **`default_models_dir()`**; default workspace **`~/LaylaWorkspace`**. Docs: ethics telemetry clarification, **`CONFIG_REFERENCE`** sandbox note. Test: **`test_plan_workspace_store`** patches **`plan_workspace_store.inside_sandbox`**.

- **Consolidation hardening:** **`autonomous_run`** restores **`engineering_pipeline_mode`**, **`clarification_reply`**, **`skip_engineering_pipeline`** (execute path → **`run_execute_pipeline`**). **`routers/agent`** late-binds **`autonomous_run`** for test mocks. SQLite: **`db_connection._resolve_db_path()`** + **`migrations._effective_migrated()`** so tests patching **`layla.memory.db._DB_PATH`** / **`_MIGRATED`** work; barrel re-exports **`_DB_PATH`**, **`_MIGRATED`**. **`services/outcome_writer.py`** holds outcome / Echo memory / patch extract / auto-learnings. Relationship codex: **`_relationship_codex_context`** + **`memory_sections.relationship_codex`**; **`codex_suggest_update`** uses **`registry.inside_sandbox`** for monkeypatch parity. **`GET /study_plans`** **`last_studied`** falls back to DB column when audit has no rows. UI bootstrap **`bindChatInputNow`**. Removed duplicate **`docs/ARCHITECTURE.md`** (table merged into root **`ARCHITECTURE.md`**); archived stub **`docs/archive/sweep_stubs/LAYLA_MODULE_SECOND_SWEEP.md`**.

- **Repo consolidation (continuation):** Tool bodies in **`layla/tools/impl/*.py`** with thin **`registry_body.py`**. SQLite split: **`layla/memory/db_connection.py`**, **`migrations.py`**, domain modules (**`learnings.py`**, **`plans_db.py`**, …), barrel **`db.py`**. HTTP: **`routers/settings.py`**, **`session.py`**, **`conversations.py`**, **`voice.py`**, **`knowledge.py`**, **`workspace.py`**, **`openai_compat.py`**, **`missions.py`**, **`paths.py`**, **`route_helpers.py`**; agent surface split **`routers/learn.py`** + **`routers/agent_tasks.py`** + **`services/agent_task_runner.py`** (included from **`routers/agent.py`**). Tiered system-head caps: **`services/prompt_tier_budget.py`** + config **`tiered_prompt_budget_enabled`**.

- **Repo consolidation (partial):** Tool implementations split into **`layla/tools/registry_body.py`** + **`sandbox_core.py`**; thin **`registry.py`** assembles **`TOOLS`**. **`routers/system.py`** holds **`/health`**, **`/usage`**, **`/version`**, **`/update/*`**, **`/doctor`**, **`/skills`**, etc.; **`/study_plans`** enriched list + **`DELETE`** live only in **`routers/study.py`** (duplicate **`main.py`** routes removed). Dead stubs removed (**`integration_sandbox`**, **`decision_engine`**, **`self_improvement`**, **`tool_orchestrator`**, **`context_builder`**, **`core/loop.py`**). **`system_head_budget_ratio`** caps system-head **`n_ctx`** slice when **`prompt_budget_enabled`**. Config: duplicate **`inference_backend`** key removed from **`runtime_config.example.json`**.

- **Relationship codex (decision + initiative + read-only tool):** System-head digest moved **immediately after identity** (before heavy memory blocks). **`decision_bias_prompt_extension(..., relationship_codex_active=...)`** nudges JSON tool decisions when codex has entities and inject is enabled. **Inline initiative** prefixes suggestions when codex is populated. Tool **`codex_suggest_update`** returns heuristic suggestions only (no write). Default **`relationship_codex_inject_max_chars`** **1000**. Tests: cap + sandbox + injection; plan-governance tests accept **`create_plan`** `**kwargs` and higher **`max_runtime_seconds`** / **`max_tool_calls`**.

- **Operator UX (memory transparency + relationship codex):** [`docs/PRODUCT_UX_ROADMAP_VS_CURRENT.md`](docs/PRODUCT_UX_ROADMAP_VS_CURRENT.md) maps a legacy “Life OS” product draft vs shipped code. **`GET/PUT /codex/relationship`** ([`agent/routers/codex.py`](agent/routers/codex.py)) + Library → Workspace → **Codex** tab (JSON editor). Optional **`relationship_codex_inject_enabled`** / **`relationship_codex_inject_max_chars`** append a capped codex digest in **`agent_loop._build_system_head`**. Knowledge panel shows **`/memory/stats`**, richer copy, and **Delete** on recent learnings via **`GET/DELETE /learnings`**. Onboarding step points at Library → Knowledge/Codex. Tests: **`agent/tests/test_codex_router.py`**. Also fixes **`format_aspects_hint`** import in **`agent_loop`** (was referencing undefined `pm`).

- **North Star gaps (fabrication IR, evaluate, recovery, discovery, retrieval, initiative):** Deterministic **`layla.geometry.machining_ir`** + tool **`geometry_extract_machining_ir`**; **[docs/FABRICATION_IR_AND_TOOLCHAIN.md](docs/FABRICATION_IR_AND_TOOLCHAIN.md)**. **`services/outcome_evaluation`** + reflection integration. **`recovery_strategy`** on failure hints + replan prompt nudge. **`project_discovery_auto_inject`** + **`services/project_discovery_hooks`**. **`memory_retrieval_min_adjusted_confidence`**, **`inline_initiative_enabled`**, **`orchestrator.decision_bias_prompt_extension`**. Tool count **189**.

- **Structured engineering partner (optional):** Config **`engineering_pipeline_enabled`**, **`engineering_pipeline_default_mode`** (`chat` | `plan` | `execute`); **`POST /agent`** fields **`engineering_pipeline_mode`**, **`clarification_reply`**. Module **`agent/services/engineering_pipeline.py`** (blocking clarifier, forced critics, refiner overwrite, governed **`execute_plan`** with **`skip_engineering_pipeline`**, mandatory validator in execute mode, ContextVar lock vs legacy **`should_plan`**). Router precedence: when enabled, **`plan_mode`** / mode **`plan`** → **`run_plan_light`**; fast path + response cache bypass for **`plan`**/**`execute`**. MCP forwards pipeline fields; Web UI mode selector + clarification panel. Docs: **`docs/STRUCTURED_ENGINEERING_PARTNER.md`**, North Star **§21**, **`ARCHITECTURE.md`**, **`PROJECT_BRAIN.md`**, **`WORKFLOW.md`**, **`docs/CORE_LOOP.md`**, **`docs/IMPLEMENTATION_STATUS.md`**, **`docs/POST_AGENT_RESPONSE_CONTRACT.md`**. Tests: **`agent/tests/test_engineering_pipeline.py`**; governance tests force **`engineering_pipeline_enabled: false`** in config overlays.

- **File checkpoints & optional Elasticsearch & chat ingest:** Pre-write snapshots (`agent/services/file_checkpoints.py`) before `write_file` / `apply_patch` / `search_replace` / `write_files_batch`; retention via `file_checkpoint_max_count` / `file_checkpoint_max_bytes`; tools `list_file_checkpoints`, `restore_file_checkpoint`; `GET /memory/file_checkpoints`, `POST /memory/file_checkpoints/restore`. Optional ES mirror (`agent/services/elasticsearch_bridge.py`) on `save_learning`, `GET /memory/elasticsearch/search`, tool `memory_elasticsearch_search` (explicit `elasticsearch_disabled` when off; warning logs on index/search errors). Chat export → `knowledge/_ingested/chats/` via `ingest_chat_export` / tool `ingest_chat_export_to_knowledge`. **Intent routing:** `agent/services/intent_routing_hints.py` (decision prompt hints + goal arg fill), `decision_engine` / `intent_detection` / `tool_recommend` mappings. Web UI **Library → Memory:** Elasticsearch search box + checkpoint list/restore. Docs: `docs/EXTERNAL_RESOURCES.md`, `docs/BACKUP_INGESTION_AND_ELASTICSEARCH.md`; tests: `test_file_checkpoints`, `test_ingest_chat_export`, `test_intent_routing_hints`, `test_elasticsearch_bridge`.

- **Plan iteration engine:** [`agent/services/engine_plans.py`](agent/services/engine_plans.py) adds **`run_plan_iteration`** / **`run_file_plan_background_loop`** — background and single-shot runs with **`file_plan_id`** call the engine (analyze vs execute next step, strict-mode analysis-only when plan not approved, 1-pass quality refinement) instead of a raw `autonomous_run` goal-only loop. Project memory schema gains **`signals`**, **`last_iteration`**, **`repo_map`**, **`preferences`**, richer default **`aspects`**; **`aspect_hint()`**; optional **[`relationship_codex.json`](agent/services/relationship_codex.py)** helpers (not injected by default).

- **File-backed structured plans (`/plan/*`):** Pydantic **`Plan` / `PlanStep`** in [`agent/services/plan_schema.py`](agent/services/plan_schema.py); CRUD under **`.layla_plans/*.json`** via [`agent/services/plan_service.py`](agent/services/plan_service.py); step runner [`agent/services/plan_executor.py`](agent/services/plan_executor.py) calls **`autonomous_run`** (no in-process TestClient); optional refinement [`agent/services/plan_refinement.py`](agent/services/plan_refinement.py) + config **`file_plan_refinement_enabled`**. Router [`agent/routers/plan_file.py`](agent/routers/plan_file.py). Continuous execution hooks **`file_plan_step_mode`** / **`file_plan_id`** on background payloads in [`agent/routers/agent.py`](agent/routers/agent.py) and [`agent/background_job_worker.py`](agent/background_job_worker.py). Stub tool **`gencad_generate_toolpath`**. Project memory: **`summarize_memory`**, **`format_aspects_hint`**, default **`aspects`** map. Tests: [`agent/tests/test_plan_file_routes.py`](agent/tests/test_plan_file_routes.py`). **`EXPECTED_TOOL_COUNT`** → **186**.

- **Planning-first:** SQLite **`layla_plans`** (`agent/layla/memory/db.py`); **`GET/POST /plans`**, **`PATCH /plans/{id}`**, **`POST /plans/{id}/approve`**, **`POST /plans/{id}/execute`** (`agent/routers/plans.py`); **`plan_mode`** responses include **`plan_id`** + **`plan_steps`**; optional **`planning_strict_mode`** (default off) blocks mutating / run-class tools in **`agent_loop`** unless the run is bound to an **approved** plan; **`plan_id`** on **`POST /agent`** and background jobs; project memory **schema v2** (`modules`, `issues`, `plans`); Web UI **Workspace → Plans**. Docs: **`ARCHITECTURE.md`**, **`PROJECT_BRAIN.md`**, **`docs/LAYLA_PREBUILT_PLATFORM.md`**, **`docs/RUNBOOKS.md`**, **`docs/POST_AGENT_RESPONSE_CONTRACT.md`**, **`docs/IMPLEMENTATION_STATUS.md`**, **`agent/runtime_config.example.json`**. Tests: **`agent/tests/test_plans_api.py`**, **`agent/tests/test_planning_strict_mode.py`**.

- **Project memory:** Per-workspace **`.layla/project_memory.json`** via [`agent/services/project_memory.py`](agent/services/project_memory.py); tools **`scan_repo`** and **`update_project_memory`**; bounded injection in **`agent_loop._build_system_head`**; config keys `project_memory_*` in [`agent/runtime_config.example.json`](agent/runtime_config.example.json) / [`agent/runtime_safety.py`](agent/runtime_safety.py). **`POST /agent`** **`understand_mode`** runs deterministic scan + cognition sync (no full LLM loop). **`plan_mode`** optionally persists into project memory. Background jobs support **`continuous`**, **`max_iterations`**, **`iteration_delay_seconds`** (in-thread and **`background_job_worker.py`**). Docs: [`ARCHITECTURE.md`](ARCHITECTURE.md), [`docs/RUNBOOKS.md`](docs/RUNBOOKS.md), [`docs/POST_AGENT_RESPONSE_CONTRACT.md`](docs/POST_AGENT_RESPONSE_CONTRACT.md), [`docs/PARITY_AUDIT.md`](docs/PARITY_AUDIT.md). Tests: [`agent/tests/test_project_memory.py`](agent/tests/test_project_memory.py). Tool count **186** (`EXPECTED_TOOL_COUNT`).

- **API contract:** [`docs/POST_AGENT_RESPONSE_CONTRACT.md`](docs/POST_AGENT_RESPONSE_CONTRACT.md) documents `POST /agent` response variants (`state.status`, `state.steps`). Router now normalizes **`state.steps`** (always an array) for empty message, fast path, no-model, and error responses; adds **`load`** + **`conversation_id`** on empty-body short-circuit; full-loop `state` gets `steps` default via `setdefault`. Tests: [`agent/tests/test_runtime_validation_plan.py`](agent/tests/test_runtime_validation_plan.py) (subprocess background cancel with fake worker, `mcp_tools_call` through HTTP + mocked decision, timeout/system_busy/tool_limit copy, optional slow live multi-tool when a model is configured; `LAYLA_TRACE_CAPTURE` writes JSON).

- **Docs:** [`docs/PARITY_BACKLOG.md`](docs/PARITY_BACKLOG.md) — maps IN-PROGRESS / PARTIAL / FUTURE parity rows to code paths and suggested tests; [`docs/PARITY_AUDIT.md`](docs/PARITY_AUDIT.md) corrects **save_for_session** to IMPLEMENTED (API + session grants + Web UI checkbox).

- **DB migrations:** `layla_projects` `cognition_extra_roots` ALTER no longer runs before the table exists (fresh `layla.db` no longer aborts `migrate()` early). **`create_project` INSERT** placeholder count fixed (9 columns / 9 values).

- **Verification & parity hygiene:** [`docs/VERIFICATION.md`](docs/VERIFICATION.md) documents the CI-parity pytest command; CI runs `pytest-cov` with a floor in [`agent/.coveragerc`](../agent/.coveragerc). [`docs/parity_manifest.yaml`](docs/parity_manifest.yaml) + [`agent/tests/test_parity_manifest.py`](../agent/tests/test_parity_manifest.py) guard `PARITY_AUDIT`-related paths/symbols. [`docs/PARITY_AUDIT.md`](docs/PARITY_AUDIT.md) updated (concurrent read-only batches implemented; sub-agents partial via `POST /agents/spawn`; MCP client stub `services/mcp_client.py` + config keys). Root-level reference tree dirs ignored in [`.gitignore`](../.gitignore). Tool count reconciled to **186** (`test_registered_tools_count.py`, `AGENTS.md`). Extracted `format_tool_steps_for_prompt` + context-window UX to [`agent/services/agent_loop_formatting.py`](../agent/services/agent_loop_formatting.py) and [`agent/services/context_window_ux.py`](../agent/services/context_window_ux.py).

- **Full improvement plan (native, no zip wiring):** Thread-safe config/hardware/aspect caches (`runtime_safety`, `orchestrator`, `agent_loop`); `invalidate_config_cache()`; blocking routes on `asyncio.to_thread`; SSE token/worker queues; inline UI tombstone when `index.html` missing; shell denylist/safe patterns + DB `tool_permission_grants`; file approval **diff** previews; HyDE + `hyde_enabled`; auto-compact on assistant turns (`shared_state.append_conv_history`); context SSE warnings + Web UI ctx bar, **⊙ Compact**, session stats row, **Skills** workspace tab, prompt **↑** history; `POST /compact`, `GET /ctx_viz`, `/session/stats`, `/history`, `/skills`; Ollama routing via `ollama_base_url` + `inference_router.ollama_http_base`; `concurrency_safe` metadata on read-only tools (batch execution future). See **`docs/PARITY_AUDIT.md`**.

- **Docs:** `docs/AI_HANDOFF_SESSION_2026-04-02.md` — session handoff for AI continuity (Web UI fixes, `window.*` export rule, `/health` coalescing, chat typing helpers, integrations zips, verification checklist); `AGENTS.md` links it for resuming sessions.

- **6-phase loop hardening (Tier 0–3):** Security, stability, and modularity improvements to the core execution pipeline.
  - **SSRF fix:** `192.168.x.x` range now blocked in `routers/agent.py` alongside existing 10.x / 127.x / 169.254.x blocks.
  - **Approval expiry:** `_write_pending()` now writes `expires_at` (now + `approval_ttl_seconds`, default 3600s); `POST /approve/{id}` returns **HTTP 410** if expired.
  - **Per-tool timeout:** `agent/core/executor.py` — wraps every generic tool dispatch in `ThreadPoolExecutor` with `tool_call_timeout_seconds` (default 60s); output capped at 256 KB with `[OUTPUT TRUNCATED]` suffix.
  - **n_ctx-proportional context budgets:** `services/context_budget.py` scales section budgets proportionally to the actual model context window (`n_ctx * 0.75`) instead of hardcoded 800-token values.
  - **New config keys:** `tool_call_timeout_seconds` (default 60), `approval_ttl_seconds` (default 3600), `hyde_enabled` (default false) — editable via Settings UI and documented in `docs/CONFIG_REFERENCE.md`.
  - **Orchestrator threshold:** Cosine similarity minimum raised from 0.15 → 0.35 to reduce false aspect matches.
  - **New core modules:** `agent/core/observer.py` (Phase 1 snapshot), `agent/core/executor.py` (Phase 4 timeout/sandbox), `agent/core/validator.py` (Phase 5 injection detection), `agent/core/loop.py` (thin orchestrator stub), `agent/core/__init__.py`.
  - **WORKFLOW.md:** Authoritative 6-phase loop contract (invariants, failure modes, termination conditions).
  - **docs/CORE_LOOP.md:** Technical spec of all 6 phases for operator and AI consumption.
  - **Cursor multi-agent tools:** 4 new MCP tools in `cursor-layla-mcp/server.py` — `delegate_task`, `poll_task`, `parallel_aspects`, `agent_handoff`.

- **Web UI:** **`/health` fetch coalescing** — concurrent callers no longer get `null` while another `fetchHealthPayloadOnce()` is in-flight (fixes Status / runtime panels stuck on skeletons). **`fetchWithTimeout`** now aborts the request when the **timeout** fires even if the caller passed an `AbortSignal` (linked controllers). **Chat UX:** one shared **`laylaShowTypingIndicator` / `laylaRemoveTypingIndicator` / phased non-stream status** (connecting → thinking → still working → preparing reply); **research** stream matches main chat (meta line, first-token + stalled hints, `fetchWithTimeout`); **Study now** uses the same typing + timeout pattern.
- **Web UI:** **Inline panel handlers** (`onclick` / `oninput` on Status, Workspace, Research, textarea, etc.) failed because the huge script wraps logic in `try{}`; function declarations are **block-scoped**, so names like `checkForUpdates` / `runKnowledgeIngest` were not on `window`. Added explicit `window.*` exports for those handlers; opening **Workspace** now refreshes the **active** subtab (default Models no longer stuck on “Loading…”).
- **Web UI:** Removed **duplicate** modal/overlay markup after `</script>` (second copies of `chat-search-overlay`, `setup-overlay`, `settings-overlay`, `batch-diff-overlay`, `diff-overlay` broke `getElementById` and could leave invisible full-screen layers stealing clicks). Initial load now calls `window.showMainPanel('status')` (bootstrap defines only `window.showMainPanel`).
- **Web UI:** Rebuilt right-hand control center as isolated `#layla-right-panel` (`.rcp-tab` / `.rcp-page`, Workspace `.rcp-subtab` / `.rcp-subpage`): `min-height: 0` on the flex column, one scroll container (`.rcp-body`), no nested tier1/ws-pane overflow trap; bootstrap delegation updated; onboarding selector points at new tabs. **Click fix:** `pointer-events: none !important` on `body::after` scanlines + `#doodle-overlay`; `#layla-right-panel` `z-index: 20` over `.main-area`; `.layout` `isolation: isolate`; right-panel tab clicks use **document capture** so they still run if something stops propagation on bubble.
- **Psychology / collaboration (non-clinical):** `docs/ETHICAL_AI_PRINCIPLES.md` §11; guardrails in `knowledge/echo-psychology-frameworks.md`; `direct_feedback_enabled` + `pin_psychology_framework_excerpt` (`runtime_safety` defaults, `runtime_config.example.json`, `config_schema` / Settings UI, `agent_loop._build_system_head`); wider `_needs_knowledge_rag` for reflective phrasing; `style_profile` **`collaboration`** snapshot (heuristic, no disorder labels); `docs/CONFIG_REFERENCE.md`, `docs/RUNBOOKS.md` (operator-local copyrighted texts); catalog [`docs/OPERATOR_PSYCHOLOGY_SOURCES.md`](docs/OPERATOR_PSYCHOLOGY_SOURCES.md) (in-repo knowledge, optional libs, research vs profiling).
- **CI & quality:** Ruff lint in CI uses full `[tool.ruff]` rules (includes **I** / import order), not only E/F/W; optional Playwright **e2e_ui** job + `agent/requirements-e2e.txt`; main pytest matrix excludes `e2e_ui`.
- **Web UI:** `BroadcastChannel('layla-health-v1')` syncs `/health` payload across tabs so header status stays fresh when another tab polls.
- **Settings & potato preset:** `EDITABLE_SCHEMA` adds **Runtime limits** (`performance_mode`, `max_runtime_seconds`, `research_max_*`, moved `max_tool_calls`); **Memory** toggles `learning_quality_gate_enabled` / `learning_quality_min_score`; `POST /settings/preset` with `{"preset":"potato"}`; Web UI preset button + study panel presets/suggestions/derive-topic endpoints; `docs/POTATO_MODE.md`.
- **Persona focus:** `POST /agent` optional `persona_focus` merges a second aspect into the system head; streaming path + Cursor MCP `persona_focus` field; transport `call_layla_*` passes it through.
- **Learnings:** optional `tags` column on `learnings`; `POST /learn/` accepts `tags`; Web UI **remember** on assistant bubbles; Discord `/note` → `/learn/` with `discord:explicit_note`.
- **Personalities:** `systemPromptAddition` restructured (voice contract + Core / Chat style / Hard limits) across `personalities/*.json`; RUNBOOKS personality editing guidance.
- **Installer / first_run:** optional potato preset prompt after hardware step.
- **Observability & golden flow:** `services/health_snapshot.py`; `GET /health` adds `active_model`, `effective_config` (sanitized + `effective_caps`), `features_enabled`, `dependencies` (Chroma vector probe when `?deep=true`); `GET /health/deps`; Web UI unified `/health` poller (60s deep interval), richer `header-system-status` (model, perf mode, LLM, deps, agent activity); [`docs/GOLDEN_FLOW.md`](docs/GOLDEN_FLOW.md); HTTP test [`agent/tests/test_golden_flow_http.py`](agent/tests/test_golden_flow_http.py); `docs/PRODUCTION_CONTRACT.md` updated.
- **Fabrication assist V1 hardening:** Pydantic **`schemas`** + typed **`errors`**; **`SubprocessJsonRunner`** + **`echo_kernel`** (real subprocess path, `PYTHONPATH` injection); session size/depth limits and **no silent corrupt JSON**; YAML load tolerates **`YAMLError`**; CLI **`--json`**, **`--dry-run`/`--explain`**, **`--runner stub|subprocess`**, **`-v`/`--debug`**, documented **exit codes 0–5**; **`continue_on_runner_error`** on **`assist()`**; tests: runner/timeout/kernel-fail, CLI E2E, session poison isolation, perf, doc link check, malformed YAML; **`pyproject.toml`** package discovery includes **`fabrication_assist*`**; CI **`pip install -e .`** + import check.
- **Web UI (pre–1.0 hardening):** Control Center panels — loading skeletons, `fetchWithTimeout`, HTTP error messages for platform/knowledge/projects/timeline/plugins/study/approvals; Health tab shows knowledge index + effective limits; header `header-system-status` from `/health`; memory search timeout + empty placeholder; double-send guard (`_laylaSendBusy` + `finally`); Study tab refresh on open.
- **Uniform depth (Tier 2):** `ARCHITECTURE.md` blockquote + `docs/README.md` technical-depth table + `.cursor/rules/layla-assistant.mdc` align with the sweep registry (`MODULE_SWEEP_STATUS` / `*_MODULE_SECOND_SWEEP.md`).
- **Uniform depth (Tier 1):** `docs/UI_MODULE_SECOND_SWEEP.md`; all rows in `docs/MODULE_SWEEP_STATUS.md` link to their `*_MODULE_SECOND_SWEEP.md`; `.cursor/rules/north-star.mdc` points AIs at the sweep registry; `PROJECT_BRAIN.md` lists UI sweep in examples.
- **`PROJECT_BRAIN.md`**: wired to the depth stack—`System Deep References`, `AI Usage Rules`, read-order link to `MODULE_SWEEP_STATUS` / per-subsystem sweeps; pointers from `docs/MODULE_SWEEP_STATUS.md`, `docs/RUNBOOKS.md`, and `AGENTS.md` quick orientation.
- **Docs (uniform technical depth)**: `docs/MODULE_SWEEP_TEMPLATE.md`; second sweeps for geometry, MCP+CLI, integrations; `docs/MODULE_SWEEP_STATUS.md` rows; `test_geometry_bridge_security.py` (bridge allowlist + sandbox, no CAD deps).
- **Geometry stack (`agent/layla/geometry/`)**: versioned `GeometryProgram` JSON (v1), executor, backends (ezdxf 2D, cadquery subprocess, OpenSCAD CLI, trimesh mesh info), optional HTTP bridge for external CAD-sequence services. Tools: `geometry_validate_program`, `geometry_execute_program` (approval), `geometry_list_frameworks`. Config: `geometry_frameworks_enabled`, `openscad_executable`, `geometry_subprocess_timeout_seconds`, `geometry_external_bridge_url`. Capabilities: `geometry_kernel_ezdxf`, `geometry_kernel_cadquery`, `geometry_kernel_trimesh`.
- **`PROJECT_BRAIN.md`**: root-level stable summary for humans/AIs (workflow discipline, doc map, pinned facts); linked from `AGENTS.md`, `docs/README.md`, `docs/RULES.md`, `.cursor/rules/north-star.mdc`.
- **Production contract & docs**: `docs/PRODUCTION_CONTRACT.md`; `docs/RULES.md`, `docs/TASKS.md`, `docs/RELEASE_CHECKLIST.md`; `GET /health` adds `effective_limits` and `response_cache_stats`; tool outcomes log at `INFO`; memory retrieval logs FTS fallback at `INFO` after Chroma failure.
- **Production-oriented defaults** (`runtime_safety` static defaults + example template): `max_tool_calls` **2**, `max_runtime_seconds` **30**, `performance_mode` **auto**, `tool_loop_detection_enabled` **true**, `completion_cache_enabled` / `response_cache_enabled` **true**, `anti_drift_prompt_enabled` **true**. CI `runtime_config.json` aligned. Key name for runtime cap remains **`max_runtime_seconds`** (not `max_run_time_seconds`).
- **Supported Python**: 3.11 and 3.12 only (`pyproject.toml` `requires-python >=3.11,<3.13`); `.python-version`; `INSTALL.bat` / `install.sh` reject 3.13+; `diagnose_startup.py` warns on unsupported versions; docs updated.
- **`GET /health`**: `knowledge_index_ready`, `knowledge_index_status`, and optional `knowledge_index_error` reflect startup knowledge indexing (observability only).
- **Dependency recovery**: `auto_pip_install_optional` defaults to **false** (safer deployments); set `true` for allowlisted auto `pip` on trusted machines. Structured `recovery` payloads unchanged for missing GGUF, voice endpoints, and `llama_cpp`.
- **Dual-model (boss/minion) routing**: `resolve_dual_model_basenames()`, `classify_task_for_routing()` + `route_default_to_chat_model`; `is_routing_enabled()` honors `chat_model_path` / `agent_model_path` and `force_dual_models` + resolvable pair; `force_dual_models` bypasses RAM gate in `resource_manager`; `/health` and `/platform/models` expose `model_routing`.

## [1.1.0] — 2026-03-19

### Full power-user upgrade pass
- **Fast chat latency path**: trivial greetings/acks now short-circuit in `routers/agent.py`; `agent_loop.py` skips history summarization when `reasoning_mode` is `none`.
- **Instant UX + cache**: streaming sends immediate `thinking` event; optional in-memory response cache (`services/response_cache.py`) via `response_cache_enabled`, `response_cache_ttl_seconds`, `response_cache_max_entries`.
- **Product endpoints**: new `agent/version.py`, `GET /version`, `GET /update/check`, and `POST /update/apply` backed by `services/auto_updater.py` (requires `allow_run` + shell approval).
- **UI product polish**: Health panel shows version and includes "Check for updates" action.
- **Smarter defaults**: added model catalog entries for Dolphin 3.0 Llama 3.3 70B, DeepSeek R1 Distill Qwen 7B, and Qwen2.5 Coder 14B.
- **Learning quality control**: `learnings.score` migration in `db.py`; `save_learning(..., score=...)`; `get_recent_learnings(..., min_score=...)`; prompt injection path reads only learnings above `learning_min_score`.

### Safety & hygiene (agent loop)
- **Tool output validation**: `services/tool_output_validator.py`; wired after real tool execution in `agent_loop.py` (skips policy / approval / loop pseudo-results)
- **Exact duplicate tool calls**: per-run `_recent_exact_calls` + `exact_call_key()`; `push_and_evaluate(..., reasoning_mode=)` lowers default repeat stop threshold (20→5) for `none`/`light` unless `tool_loop_stop_threshold` is overridden
- **Sandbox Python**: `python_runner` uses isolated `mkdtemp` + cleanup; optional `sandbox_python_memory_limit_mb` + `preexec_fn` RLIMIT_AS on POSIX
- **Knowledge ingest**: content-hash dedup via `.hash` sidecars; optional injection guard (`doc_injection_guard_enabled`) with data framing + redaction
- **Retrieval context**: `max_chars_per_source`, `retrieval_line_overlap_threshold` (Jaccard on words) in `_build_retrieved_context_impl`
- **Writes / patches**: `write_file_max_bytes`, `write_file_explosion_factor`; `max_patch_lines` for `apply_patch`
- **Decisions**: `action: "none"` in `decision_schema` + no-op step in loop
- **Telemetry**: skip `reasoning_mode=none` events unless `telemetry_log_trivial`
- **Routing**: `model_router` warns when selected GGUF path missing; clearer `llm_gateway` fallback warning

### Power-user phased integration
- **Sandbox runners**: `services/sandbox/shell_runner.py`, `services/sandbox/python_runner.py` — timeouts from `sandbox_runner_timeout_seconds` / `sandbox_python_timeout_seconds`; optional `shell_restrict_to_allowlist` + `shell_allowlist_extra`; `shell` / `run_python` tools delegate with subprocess fallback
- **Tool args validation**: `services/tool_args.py` + `tool_args_validation_enabled`; structured errors before dispatch when LLM supplies `args`
- **Code intelligence**: `services/code_intelligence.py`, tool `search_codebase` (graph + semantic); `coding_model_large_context` + `coding_large_context_threshold` in `select_model()`
- **Retrieval**: weighted hybrid fusion (`retrieval_hybrid_*`); `coding_boost` for `reasoning_mode` deep; optional BGE reranker (`use_bge_reranker`, `bge_reranker_model`)
- **Doc ingestion**: `services/doc_ingestion.py`; `GET /knowledge/ingest/sources`, `POST /knowledge/ingest`; Knowledge Manager UI in platform Knowledge panel
- **Learning quality**: `distill.score_learning_content` / `passes_learning_quality_gate`; `save_learning` rejects when `learning_quality_gate_enabled`
- **Multi-agent hints**: `services/agent_roles.py`; `multi_agent_orchestration_enabled` injects coordination snippet for `reasoning_mode` deep (prompt-only, single LLM)

### Final polish (Phase 3)
- **Completion cache metrics**: hit/miss counters, `get_cache_stats()`; exposed on `GET /health` as `cache_stats`; optional UI badge when `localStorage.layla_show_cache_stats === '1'`
- **Reasoning stability**: `stabilize_reasoning_mode()` (deep→light smoothing); `last_reasoning_mode` on agent state; streaming path uses same global smoothing
- **Retrieval**: `build_retrieved_context(..., reasoning_mode=)` skips fused retrieval for `light` + query length &lt; 20
- **Telemetry → routing**: `get_user_profile()` (simple/coding ratios); soft bias in `select_model()` toward chat/default when `simple_ratio` &gt; 0.7 (telemetry disabled → no bias)
- **Setup status**: `resolved_model`, `model_route_hint` (`code` / `chat` / `reasoning`); header shows resolved filename + hint

### Phase 3 — Performance & adaptive reasoning
- **Reasoning classifier** (`services/reasoning_classifier.py`): per-turn `none` / `light` / `deep`; `deep` capped to `light` when `performance_mode` is `low`; `none` skips planner; `light`/`none` skip streaming self-reflection
- **`reasoning_mode`** on agent state; forwarded in `POST /agent` JSON, stream `done` events, and `/research` responses; Web UI `#reasoning-mode-badge`
- **Completion cache**: key includes model + temperature + max_tokens; `completion_cache_max_entries` config (default 500)
- **Local telemetry**: `telemetry_events` table + `services/telemetry.py` (`telemetry_enabled`, default on); logged at end of `autonomous_run` (including `system_busy` / `plan_completed` paths)
- **Fix**: `effective_history` initialized before `_build_system_head` in the non-stream reason path (was `UnboundLocalError`)

### Hardening
- `GET /setup_status` adds `model_valid`; UI re-opens setup when config points at a missing file
- `POST /agent` returns `error: no_model` and `action: open_setup` when the model is not ready
- `llm_gateway`: routing prompt ContextVar + `_effective_model_filename` uses `select_model` for all completions (skips internal decision/critic prompts)
- Optional `completion_cache_enabled` + TTL for non-stream completions
- `get_best_llm_filename_for_task` (capability-aware) wired into `select_model`
- Context: `pinned_context` (last user message, last tool result, session summary), memory chunk dedup
- `output_polish`: skip tool-style JSON (`"ok":` / `"error":` leaders)
- Plugins: stricter YAML/capability validation; `/platform/plugins` includes `capabilities_by_type`
- Setup UI: recommended model highlight, download retry, catalog `recommended` from hardware tier

---

## [2.0.0] — 2026-02-22

### Major — The Character Update

#### Aspects
- Renamed Neuro → **Cassandra** (unfiltered oracle; no filter between perception and output)
- All six aspects rewritten with 300–600-word `systemPromptAddition` character definitions
- Fixed critical bug: `systemPromptAddition` was silently truncated to 80 chars — now fully injected
- Added per-aspect symbols: ⚔ Morrigan, ✦ Nyx, ◎ Echo, ⚡ Eris, ⌖ Cassandra, ⊛ Lilith
- Deliberation prompt rewritten with per-aspect voice cues so the model knows the register
- `build_standard_prompt` now includes a character anchor line
- `system_identity.txt` rewritten as a deep foundational Layla identity document
- `.identity/self_model.md` created — Lilith's self-model, injected only when Lilith is active

#### Capabilities
- Added 8 new tools: `json_query`, `diff_files`, `env_info`, `regex_test`, `git_add`, `git_commit`, `save_note`, `search_memories`
- Echo now accumulates session-pattern summaries every 5 turns across all aspects
- Memory bundle export/import: `/memory/export` (ZIP), `/memory/import` (merge)
- Model download wizard in `first_run.py`: interactive picker, progress bar, 5 recommended models
- `Download-Model.ps1` rewritten: interactive model picker with real HuggingFace open model links

#### Knowledge Base
- Added 6 aspect-specific knowledge docs: `morrigan-engineering.md`, `nyx-research.md`,
  `echo-behavioral-patterns.md`, `eris-creative-thinking.md`,
  `lilith-ethics-autonomy.md`, `cassandra-pattern-perception.md`

#### UI
- Aspect buttons now show symbols (⚔ ✦ ◎ ⚡ ⌖ ⊛) instead of raw HTML codes
- Header aspect badge updates symbol on aspect switch
- Improved aspect descriptions for all six

#### Infrastructure
- Fixed `start-layla.ps1`: `cursor-jinx-mcp` → `cursor-layla-mcp`
- Fixed `IMPLEMENTATION_STATUS.md`: stale `agent/jinx/` path → `agent/layla/`
- `SETUP-AND-TEST.ps1` and `PASTE-AND-RUN.ps1` rewritten: no stale refs, cleaner output
- `/memory/stats` endpoint for memory state inspection
- Memory router wired into `main.py`

---

## [Unreleased]

### Added
- **Task-aware model routing**: when `tool_routing_enabled` and task models are configured, `autonomous_run` sets `model_override` from `model_router.classify_task(goal, context)`; `llm_gateway._get_llm()` loads per-GGUF path (primary + `coding_model` / `reasoning_model` / `chat_model`). `model_router.select_model()` ties `llm_model_coding` capability (Magicoder id) to benchmarks and `coding_model`.
- **`performance_mode`** (`low` | `mid` | `high` | `auto`) in `system_optimizer.get_effective_config()`: missing config defaults to `mid` (backward compatible); explicit `auto` maps from `hardware_detect` tiers. Adjusts `n_ctx`, tool limits, cross-encoder, planning depth, cognitive workspace (runtime only, never persisted).
- **`models` block** in `runtime_config.example.json` (`default`, `code`, `fast`, `fallback`) with `magicoder` alias → known Magicoder GGUF basename under `models_dir`.
- **`llm_model_coding`** capability in `capabilities/registry.py` (`magicoder`, `default_coding` impls).
- **Plugin YAML `capabilities`**: `plugin_loader` registers `CapabilityImpl` entries via `register_implementation`.
- **Startup capability benchmarks**: when `benchmark_on_load`, background thread runs `benchmark_suite` for `embedding` + `vector_search`.
- **`services/output_polish.py`** (`polish_output`) applied to final agent replies and SSE stream completion in `routers/agent.py`.
- **Web UI**: Stop button (`AbortController` on `/agent`), Regenerate label on retry; **`GET /platform/plugins`** includes `capabilities_added`.
- **Tests**: `tests/test_capability_routing.py`; `pytest.ini` timeout 120s for slow first embedder load.
- **LLM lock**: `threading.RLock` for `llm_serialize_lock` / `_llm_lock` to allow nested model load during `autonomous_run` without deadlock.
- First-run onboarding (4-step guided tour)
- Model readiness banner
- Keyboard shortcut reference in Help panel
- Improved error messages (`formatAgentError` for 500/503/network)
- Empty state copy for study plans and approvals panels
- Loading skeletons for Health, Models, Knowledge panels
- Focus management (input after send, restore on modal close)
- Responsive layout (sticky header, mobile sidebar with hamburger)
- Accessibility (aria-label on icon buttons, focus-visible styles)
- Typography scale (--text-xs/sm/base/lg, --heading)
- Try-this suggestions (quantum entanglement, Python hello world chips)
- Destructive action confirmations (clear chat, delete session)
- Undo toast for approvals (write_file, apply_patch)
- Input affordances hint (attach, paste, Ctrl+K)
- Aspect switching feedback toast
- Inline docs mount (`/docs`), Config Reference link in Settings
- Troubleshooting section in Help panel and README
- ChromaDB FTS fallback when vector store fails
- TTS degradation (speakReply wrapped in try/catch)
- Health dashboard (db_ok, chroma_ok, uptime)
- Logging (LOG_LEVEL, LAYLA_LOG_JSON env)
- Saved workspaces (localStorage presets)
- Custom prompt prefixes (config + UI)
- PWA manifest
- ChromaDB as sole vector store (FAISS dual-write removed); learnings now linked via `embedding_id`
- `instructor` integration for grammar-constrained JSON output in agent loop
- Embedding-based aspect routing via cosine similarity (replaces keyword substring scoring)
- Overlap-aware document chunking via `langchain-text-splitters`
- `nomic-embed-text` as default embedding model (768 dim, replaces `all-MiniLM-L6-v2`)
- Tool dispatch table replacing 700-line if-elif chain
- Paginated `/learnings` and `/audit` API endpoints
- `Dockerfile` and `docker-compose.yml`
- GitHub Actions CI workflow
- `pyproject.toml` with ruff config
- Knowledge graph edges via cosine-similarity linking
- Open WebUI integration documentation

### Fixed
- `migrate()` called on every DB function; now runs once at startup with version guard
- Mission state reset on every `/research_mission` call (broken resume); state is now preserved for `next_stage=True`
- `copy_source_to_lab` now excludes `.git`, `.venv`, `node_modules`, `__pycache__`, and files over 5 MB
- `allow_write=True` in research intelligence stages changed to `allow_write=False`
- Sandbox path check uses `Path.relative_to()` consistently (was string prefix match)
- Wikipedia slug construction now uses full topic name with proper URL encoding
- `apply_patch` now uses pure-Python `unidiff` library (no system `patch` binary required on Windows)
- Distillation re-embeds merged learnings into Chroma (previously vector store diverged from DB)
- `C:\github` hardcoded default paths replaced with `Path.home()`

### Changed
- Internal package renamed from `agent/jinx/` to `agent/layla/`
- MCP server renamed from `cursor-jinx-mcp/` to `cursor-layla-mcp/`; tool renamed `chat_with_jinx` -> `chat_with_layla`
- All identity references anonymized for public release
- Dependency pins tightened: `llama-cpp-python`, `chromadb`, `apscheduler`, `sentence-transformers`
- Removed unused `httpx` and `requests` dependencies

### Removed
- `personalities/ishtar.json` (NSFW merged into Lilith with keyword-toggle)
- `faiss-cpu` dependency
- Hardcoded personal paths and identifiers throughout codebase

---

## [0.1.0] - 2024-01-01

### Added
- Initial public release
- FastAPI agent server with GGUF/llama-cpp-python backend
- Multi-aspect personality system (Morrigan, Nyx, Echo, Eris, Lilith, Cassandra)
- Tool loop: read_file, write_file, list_dir, grep_code, glob_files, git_*, shell, run_python, apply_patch, fetch_url
- Approval-gate for dangerous tools
- SQLite memory (learnings, study plans, audit, aspect memories, capability tracking)
- FAISS/ChromaDB vector search over learnings and knowledge docs
- Research lab with staged pipeline (mapping, investigation, verification, distillation, synthesis)
- Study plans with autonomous study steps and wakeup greeting
- Cursor MCP server
- Web UI (dark occult aesthetic, streaming, aspects panel, approvals, study plans)
- OpenAI-compatible `/v1/chat/completions` endpoint
