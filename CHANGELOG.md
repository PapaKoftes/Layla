# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## Unreleased

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
