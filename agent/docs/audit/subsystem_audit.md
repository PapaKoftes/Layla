# Subsystem Audit — Layla

> Generated 2026-05-12 (Phase A audit pass).
> Ground truth for downstream documentation, plan reconciliation, and repair work.
> Author note: classifications follow the rubric in the task brief. REAL = code exists, wired into a production path, exercised by tests. SCAFFOLD = code exists but production callers are absent or only the router/tests import it. PARTIAL = some real behaviour + some stub. MISSING = referenced in plan/docs but no file exists.

---

## Summary

| Status | Count |
|--------|-------|
| REAL | 28 |
| PARTIAL | 14 |
| SCAFFOLD | 9 |
| MISSING | 12 |
| Total classified | 63 |

`run_all_checks.py` last reported `confidence_pct: 100` (11 PASS, 0 WARN/FAIL, 854 tests pass), but the `real_assertions` subscore tells a more honest story: **1/3 real assertions pass** (`memory_router_used=true`, `repo_index_populated=false`, `config_cache_importable=false`). The high-level confidence number obscures real gaps. (`agent/scripts/last_report.json:5-9`).

---

## Key findings (top 10)

1. **Memory router is a chokepoint by name, not by reality.** `services/memory_router.py:73-87` exposes `save_learning` / `save_aspect_memory` / `save_outcome` pass-throughs. Only 4 production modules use them (`reflection_engine.py:112`, `outcome_writer.py:10,102,111,316`, `knowledge_distiller.py:21`, `layla/memory/distill.py:126`). Meanwhile, ~33 files import `layla.memory.db.save_learning` / `layla.memory.learnings.save_learning` directly, completely bypassing the router. `scripts/check_wiring.py` only asserts that the router has *any* production importer; it does not assert the inverse (that nothing bypasses it).
2. **No 5-layer memory stack.** Plan Phase 11 calls for Qdrant + NetworkX + Codex + episodic + cache. Reality: ChromaDB-only vectors (`layla/memory/vector_store.py:145`), a single `knowledge_graph.graphml` file (`layla/memory/knowledge_graph.graphml` exists but the graph is barely wired), no `layla/codex/` module, no Qdrant adapter, no cache layer.
3. **No `layla/codex/` and no `layla/ingestion/` and no `layla/scheduler/` modules.** All three are top-line deliverables in plan Phases 11-14 (`logical-inventing-lampson.md:1414-1517`). `Glob agent/layla/codex/**` and `agent/layla/ingestion/**` and `agent/layla/scheduler/**` all return zero files. Scheduling lives ad-hoc inline inside `main.py:384-587`.
4. **No debate / council / tribunal engine.** North-star calls these "first-class". Grep across the whole `agent/` tree finds no production references to `debate|tribunal|council` outside tests, docs, or the plan file. The aspect engine only swaps personas serially (`orchestrator.py:1-80`, `services/aspect_behavior.py`).
5. **AirLLM and KB-builder are SCAFFOLDS with feature-flagged deps.** `services/airllm_runner.py:1-60` is 319 lines of careful wrapper code, but `airllm` is not in `requirements.txt`, default config is `airllm_enabled=False`, and the only production importer is `routers/intelligence.py`. Same shape for `services/kb_builder.py` (Unstructured/STORM/GraphRAG all optional, none in `requirements.txt`).
6. **Repo indexer is populated but `repo_index_populated=false` in last report.** `services/repo_indexer.py` is real, scheduled (`main.py:501-517`, every 30 min) and tested. But last_report.json says `repo_index_populated=false`. Likely a workspace-root config issue: `sandbox_root` empty in the env that runs `check_repo_index`. Real code, broken signal.
7. **Prompt optimizer is REAL and wired into the autonomous loop.** `agent_loop.py:3081-3097` reads `prompt_optimizer_enabled` (default true) and rewrites `goal`. **But** `goal_original` is captured (line 3078) and then never re-used downstream as a guard — the optimised goal becomes canonical. This is the "preserving original_goal" gap the task brief asked about: the variable exists, the protection does not.
8. **LLMLingua wired but heuristic-only by default.** `agent_loop.py:5443` calls `compress_conversation_history`. `services/prompt_compressor.py` declares Tier-1 LLMLingua but the library is not in `requirements.txt`; in practice only the Tier-3 TF-IDF heuristic runs. Functionally compressing, but not the LLMLingua claim made in plan Phase 6.
9. **Streamlit dev console is gone.** No `streamlit` references anywhere in `agent/`. The only UI is `agent/ui/index.html` + the vanilla-JS app (`agent/ui/js/layla-app.js`, 4024 lines — a monolith, despite plan Phase 3 calling for code-splitting at 176 KB).
10. **Install/first-run path exists; `/setup/*` endpoints exist; `agent/ui/setup.html` does NOT.** `routers/settings.py` exposes `/setup_status`, `/setup/models`, `/setup/download`, `/setup/auto` (lines 26-367). The setup wizard is embedded in the main `index.html` (modal at line 74) and `ui/js/layla-wizard.js`, not a separate file. Plan doc references to `agent/ui/setup.html` are stale.

---

## Full subsystem table

### Memory & Knowledge

| Subsystem | Status | Evidence | Gap-to-vision |
|---|---|---|---|
| Memory router | PARTIAL | `services/memory_router.py:1-499`; production importers: `services/reflection_engine.py:112`, `services/outcome_writer.py:10,102,316`, `services/knowledge_distiller.py:21`, `layla/memory/distill.py:126`. **Bypassed by ~33 files** importing `layla.memory.db.save_learning` directly (incl. `agent_loop.py`, `services/study_service.py`, `services/initiative_engine.py`, `routers/learn.py`, `services/cognitive_workspace.py`). | Chokepoint is voluntary, not enforced. Phase 11 plan says "no module writes directly to a layer" — reality is the opposite. |
| Vault filesystem (Obsidian-shaped MD mirror) | PARTIAL | `services/obsidian_sync.py:19` (VAULT_SUBDIR="obsidian"), `routers/obsidian.py` mounted at `main.py:843`. Vault is *optional outbound sync* of `knowledge/` to a user-supplied Obsidian path, not a structural mirror Layla uses internally. | North-star asks for "Obsidian-shaped markdown mirror" as the primary knowledge surface. Today it's a one-way export connector. |
| Codex schema (Person/Project/Concept/Event/Skill) | PARTIAL | `agent/schemas/entity.py:32-48` defines EntityType enum covering all 5 + more. `services/relationship_codex.py`, `services/personal_knowledge_graph.py`, `routers/codex.py` exist. **No** `layla/codex/codex_db.py`, no `layla/codex/linker.py` (plan files). Entities live in `layla/memory/db.py` tables. | Schema exists at dataclass level; canonical codex module called for by Phase 11 does not. |
| Episodic memory (`tool_calls`, `runs`) | REAL | `core/executor.py:183-245` (`record_tool_call`, INSERT into `tool_calls`). `routers/tools_history.py:26-83` exposes `/tools/history` + `/tools/analysis`. Tests: `tests/test_tool_tracing.py` (marked endpoint/slow). | Solid. Matches Phase 0.2 spec. |
| Vector store (Chroma) | REAL | `layla/memory/vector_store.py:134-207` PersistentClient, dimension mismatch guard, knowledge indexer launched from `main.py:222-241`. Used by `services/retrieval.py`, `agent_loop.py`, 8 other files. | Wired and populated. Phase 11 wants Qdrant; ChromaDB still in use. |
| BM25 / hybrid retrieval | REAL | `requirements.txt:35` rank-bm25; `services/retrieval.py`, `services/keyword_search.py`, `services/context_builder.py` all import BM25 path. | Real and active. |
| Reranker | MISSING | Grep `reranker|rerank|cross_encoder` across `agent/` → no matches. | Plan Phase 4.2 ("Retrieval Ranking by Confidence") not implemented. |
| LLMLingua compression | PARTIAL | `services/prompt_compressor.py:1-517` declares Tier-1 LLMLingua, Tier-2 LongLLMLingua, Tier-3 heuristic. `agent_loop.py:5443` calls `compress_conversation_history`. `llmlingua` package NOT in `requirements.txt`; in practice only Tier-3 (TF-IDF) runs. | Plan Phase 6 claims LLMLingua "wired" — only the fallback path is. |
| Prompt optimizer | PARTIAL | `services/prompt_optimizer.py:1-476` real; wired into `agent_loop.py:3081-3097`. **`goal_original` captured at 3078 but never re-used to preserve the user's authored text in subsequent stages** — the optimised goal becomes canonical for memory, planning, and reflection. | The "preserve `original_goal`" guard the brief asks about does not exist downstream. |
| Embedding warmup | REAL | `main.py:327-351` runs `embedding_cache_warmup`; reads recent 5000 learnings, pre-embeds 2000. Default ON. | Matches Phase 0.5 spec. |

### Aspects & Debate

| Subsystem | Status | Evidence | Gap-to-vision |
|---|---|---|---|
| 6-aspect engine | REAL | `personalities/{morrigan,nyx,echo,eris,cassandra,lilith}.json` at repo root (loaded by `orchestrator.py:13-90`); `services/aspect_behavior.py:1-224` for per-aspect reasoning depth, length, refusal topics. All 6 used in `agent_loop.py` (lines 788, 815, 853, 861, 3137, 3274). | Personas present and parametrised; voice is real, behaviour parameters real. |
| Debate / Council / Tribunal | MISSING | Grep `debate|tribunal|council` across `agent/**` → zero matches outside test fixtures/docs/the plan. No multi-aspect deliberation runtime. | North-star "first-class". Today: solo aspect per turn. |
| Aspect-tool ordering | SCAFFOLD | `services/aspect_behavior.py:146` returns step caps per aspect; tools are not aspect-routed. | Plan implies aspects bias tool choice; not implemented. |
| Aspect-specific model routing | SCAFFOLD | `services/model_router.py` exists (551 lines) but routes by reasoning_mode + task_type, not aspect. No `aspect_id`-keyed routing visible. | Plan §1.5 calls for per-aspect voice/model differentiation. |
| Voice adjustment per aspect | REAL | `services/tts.py` + `routers/voice.py` per-aspect voice settings; `ui/index.html:174-258` aspect buttons. | Voice is real (kokoro-onnx in requirements:44). |

### Models & Inference

| Subsystem | Status | Evidence | Gap-to-vision |
|---|---|---|---|
| Model router | REAL | `services/model_router.py` (551 lines); production importers: `agent_loop.py`, `routers/system.py`, `routers/agent.py`, `services/llm_gateway.py`, `services/inference_router.py`, `services/coordinator.py`, `services/intent_router.py`, `services/tool_policy.py`, `capabilities/registry.py` + 7 more. | Solid. |
| Inference router | REAL | `services/inference_router.py` (427 lines); production importers: `routers/system.py`, `services/llm_gateway.py`, `services/system_doctor.py`, `services/agent_task_runner.py`. | Solid. |
| LLM gateway | REAL | `services/llm_gateway.py` (805 lines); 26 importers including `agent_loop.py`, `core/executor.py`, `services/planner.py`, `services/inference_router.py`, `main.py:269-296` (queue worker + prewarm). | Hub of inference. |
| llama-cpp-python backend | REAL | `requirements.txt:17` `llama-cpp-python>=0.3.1,<0.4`; backend dispatch in `services/inference_router.py`. | Wired. |
| Ollama backend | PARTIAL | Backend referenced in `services/inference_router.py` and `OLLAMA.md`; no first-class connection probe. | Works if running externally. |
| OpenAI-compatible backend (cluster) | REAL | `routers/openai_compat.py` mounted at `main.py:838`; emits OpenAI-compatible `/v1/chat/completions`. **Inbound** compat for the cluster use-case; outbound OpenAI calls only for tests. | Inbound side covered. |
| AirLLM | SCAFFOLD | `services/airllm_runner.py:1-319`; only importer is `routers/intelligence.py`. `airllm` NOT in `requirements.txt`; default `airllm_enabled=False`. Module is lazy and never errors. | Plan Phase 6 marks `⬜ scaffolded; deps not in requirements.txt`. Audit confirms. |
| Expert routing (per-task) | MISSING | Grep `expert_routing|per_task_model` → no files. | Phase 4.1 dual-model split not implemented as a per-task assignment layer. |
| Model catalog | REAL | `agent/models/model_catalog.json` with tier tags (`category: general/coding/reasoning/creative/fast/flagship`, `uncensored` boolean, `ram_required`, `vram_required`). | Valid and rich. |
| Model downloader | REAL | `install/model_downloader.py`; called by `install/run_first_time.py`, `install/installer_cli.py`. | Wired. |
| Model selector | REAL | `install/model_selector.py`; called by `install/run_first_time.py`. | Wired. |

### Hardware & Resource Policy

| Subsystem | Status | Evidence | Gap-to-vision |
|---|---|---|---|
| Hardware detect | REAL | `services/hardware_detect.py:1-427`; production importers: `main.py:208`, `agent_loop.py`, `services/llm_gateway.py`, `services/model_recommender.py`, `services/worker_pool.py`, `services/task_budget.py`, `install/installer_cli.py`, `install/hardware_probe.py`, `first_run.py`, `runtime_safety.py`, `services/health_snapshot.py`, `services/system_doctor.py`, `services/system_optimizer.py` (14 files). | Heavily wired. |
| Hardware-aware startup | REAL | `main.py:206-219` runs detect+recommend at startup, logs tier; `hardware_aware_startup` config flag honoured. No `services/hardware_aware_startup.py` file (the brief asks for one) — logic lives inline in `main.py`. | File the brief expects does not exist; the *behaviour* does. |
| Idle scheduler | MISSING | Grep `idle_scheduler` → no matches. Plan calls for "idle-aware background work"; today it's a coarse process-name skip in `main.py:82-102` (`_SCHEDULER_SKIP_PROCESSES`) + the activity-window guard. | No real idle/load detection. |
| APScheduler integration | REAL | `main.py:384-587`: BackgroundScheduler with jobs `mission_worker` (2 min), `background_reflection` (5), `background_codex` (10), `background_memory_consolidation` (30), `background_initiative` (30), `background_memory_cleanup` (24 h), `repo_reindex` (30), `_scheduled_study_job`, `intelligence` (60), `rl_preference_update` (30). | Solid. But lives in lifespan rather than in a `layla/scheduler/` module as plan Phase 14 prescribes. |
| Repo indexer wiring | REAL | `services/repo_indexer.py:1-532`; called from `main.py:369-381` (startup) and `main.py:501-517` (30-min reindex). Tests in `tests/test_repo_indexer.py`. **But** `last_report.json:7` says `repo_index_populated=false` — wiring real, signal broken (likely missing `sandbox_root` at check time). | Code real; check broken. |
| Embedding cache warmup | REAL | `main.py:327-351`; `voice_stt_prewarm`/`voice_tts_prewarm` optional (`main.py:354-365`). | Solid. |

### Install & First-Run

| Subsystem | Status | Evidence | Gap-to-vision |
|---|---|---|---|
| First-run wizard | REAL | `install/run_first_time.py:1-40` orchestrates `setup_existing_model → installer_cli → first_run → diagnose_startup`. | Working. |
| Hardware probe | REAL | `install/hardware_probe.py`; called from `install/installer_cli.py`. | Wired. |
| Installer CLI | REAL | `install/installer_cli.py` + `install/packs/{e2e,voice,browser}.json`. | Wired. |
| `/setup/*` HTTP endpoints | REAL | `routers/settings.py:26` `/setup_status`, `:133` `/setup/models`, `:191` `/setup/download`, `:367` `/setup/auto`. | Real. |
| `agent/ui/setup.html` | MISSING | `Glob agent/ui/setup.html` → no file. The wizard is embedded in `agent/ui/index.html:74` (modal) + `ui/js/layla-wizard.js`. | Brief asks for a separate file; that pattern was not adopted. Not a real gap — just stale doc. |

### Safety & Transparency

| Subsystem | Status | Evidence | Gap-to-vision |
|---|---|---|---|
| Sandbox / runtime_safety | REAL | `agent/runtime_safety.py` (34 KB, 1000+ lines). Config keys: `allow_run`, `allow_write`, `allow_network`, `autonomous_allow_network` (line 327), `hooks_require_allow_run` (391). | Solid. |
| Trust tiers | PARTIAL | `services/maturity_engine.py:232-256` `get_trust_tier`; config key `autonomy_trust_tiers_enabled` (default False, `runtime_safety.py:460`). | Code exists, default off, used by `background_initiative` gate (`main.py:429`). |
| Tool permissions | REAL | Threaded through `core/executor.py`, `services/tool_policy.py`, `runtime_safety.py`. | Solid. |
| `/health` endpoint + degraded counter | REAL | `routers/system.py:179` (`/health`), `:385` (`/health/context_budget`), `:404` (`/health/trace`), `:436` (`/health/deps`); `services/degraded.py:8-17` `mark_degraded`/`get_degraded`. | Solid. |
| Activity transparency panel (UI) | PARTIAL | `ui/js/layla-autonomous.js` exists; `ui/js/layla-perf.js` exists. Real-time progress emit from `agent_loop` partial. | Some plumbing, UX coverage uneven. |
| Audit log of rail-lifts | REAL | `main.py:708-722` (`_audit` writes flat audit.log + sqlite `log_audit`); `agent/.governance/audit.log`. | Solid. |

### UI

| Subsystem | Status | Evidence | Gap-to-vision |
|---|---|---|---|
| Vanilla JS app | PARTIAL | `ui/js/layla-app.js` is **4024 lines** — single monolith. Plan Phase 3.1 calls for code-splitting at 176 KB. | Real but mass exceeds plan target. |
| Threads panel | REAL | `ui/js/layla-conversations.js`, `ui/index.html:220-225` left rail with search. | Real. |
| Artifacts panel | REAL | `ui/js/layla-artifacts.js`; `routers/agent.py` extracts artifacts server-side (per last commit `d7382c8 feat(artifacts)`). | Real. |
| Codex/memory browser | REAL | `ui/js/layla-memory.js`; `routers/memory.py`, `routers/codex.py` mounted. | Real. |
| Plan visualisation (Gantt) | REAL | `ui/js/layla-plan-viz.js` exists. | Functionally present. |
| Autonomous monitoring | PARTIAL | `ui/js/layla-autonomous.js` exists; streaming progress in `agent_loop` exists but coverage of events vs spec is incomplete. | Real but partial. |
| Global search | REAL | `ui/js/layla-search.js`; `routers/search.py` mounted (`main.py:842`). | Real. |
| Voice UI | REAL | `ui/index.html` voice controls; `routers/voice.py`; STT via `faster-whisper` (requirements:42), TTS via `kokoro-onnx` (requirements:44). | Real. |
| Settings UI | PARTIAL | `routers/settings.py`; no dedicated `layla-settings.js` (Phase 1.6 plan file). Settings surface via wizard + ad-hoc forms in `index.html`. | Partial. |
| Streamlit dev console | MISSING | No `streamlit` references in `agent/`. Removed at some point. | Doc/plan reference stale. |

### Remote & Multi-Node

| Subsystem | Status | Evidence | Gap-to-vision |
|---|---|---|---|
| Syncthing sync | SCAFFOLD | `services/syncthing_sync.py:1-259`; `routers/sync.py` mounted at `main.py:846`. **Zero production importers in the agent codebase** (`grep` returned no files). Syncthing daemon not bundled. | Plan marks ⬜ scaffolded; confirmed. |
| mDNS discovery | MISSING | Grep `mDNS|zeroconf` → no matches. | Not implemented. |
| WireGuard / mesh | MISSING | Grep `wireguard|mesh` → no matches. | Not implemented. Only `services/tunnel_manager.py` exists (purpose unclear). |
| PWA mobile shell | REAL | `ui/manifest.json`, `ui/sw.js` served from `main.py:867`. | Real. |
| Pairing flow | MISSING | No pairing UI/route discoverable. | Not implemented. |

### Ingestion & KB

| Subsystem | Status | Evidence | Gap-to-vision |
|---|---|---|---|
| Universal ingestion pipeline (`layla/ingestion/`) | MISSING | `Glob agent/layla/ingestion/**` → empty. | Phase 12 deliverable absent. Ingest scattered across `services/data_importers.py`, `services/doc_ingestion.py`. |
| Unstructured.io | SCAFFOLD | Referenced in `services/kb_builder.py`, `scripts/check_imports.py`. NOT in `requirements.txt`. | Optional. |
| spaCy NER | SCAFFOLD | Referenced in `services/graph_reasoning.py`, `services/kb_builder.py`. NOT in `requirements.txt` (commented out lines 115 and 169). | Optional. |
| Whisper STT | REAL | `services/stt.py` uses `faster-whisper` (`requirements.txt:42`); `routers/voice.py` mounted. | Real. |
| Kokoro TTS | REAL | `services/tts.py` uses `kokoro-onnx` (`requirements.txt:44`). | Real. |
| Web ingest (trafilatura) | REAL | `requirements.txt:21`; used in `layla/tools/impl/general.py`, web tools. | Real. |
| KB builder STORM/GraphRAG | SCAFFOLD | `services/kb_builder.py:1-741`; only importer `routers/intelligence.py`. STORM/GraphRAG/`knowledge-storm`/`graphrag` not in `requirements.txt`. | Plan marks ⬜ scaffolded; confirmed. |
| Obsidian connector | PARTIAL | `services/obsidian_sync.py`, `routers/obsidian.py` mounted. One-way sync. | Plan Phase 5.1 partial. |

### Observability

| Subsystem | Status | Evidence | Gap-to-vision |
|---|---|---|---|
| Prometheus metrics | MISSING | Grep `prometheus|Prometheus|structlog` → 0 files. `prometheus_client` not in `requirements.txt`. No `services/metrics.py`, no `routers/metrics.py`. | Phase 13 entirely absent. |
| structlog | MISSING | Grep `structlog` → 0 files. Stdlib `logging` only. `services/task_context.py:81` `install_filter` adds task-context dict to log records (real — `agent_loop.py:3104` calls it). | Partial workaround via task_context filter, not full structlog. |
| Crash dumps | PARTIAL | `agent/.governance/audit.log`; no `~/Layla/crashes/` discovered. | Audit log real, crash dumps not. |
| `run_all_checks.py` | REAL | `scripts/run_all_checks.py`; orchestrates the 11 checks listed in `last_report.json`. | Real. |
| `services/observability.py` | REAL | 230 lines; `log_agent_started`/`log_agent_shutdown` called from `main.py:170,594`. | Real but minimal. |
| `services/telemetry.py` | REAL | 147 lines; `services/langfuse_export.py`, `services/otel_export.py` also present. | Real export plumbing. |
| `services/performance_monitor.py` | REAL | File exists; production importers TBD (UNVERIFIED depth). | Likely real. |

### Tools

| Subsystem | Status | Evidence | Gap-to-vision |
|---|---|---|---|
| read/write/list/grep tools | REAL | `layla/tools/impl/file_ops.py`, `layla/tools/domains/file.py`; registered via `layla/tools/registry.py`. Validated at startup `main.py:250-253`. | Solid. |
| run_shell, run_python | REAL | `services/sandbox/shell_runner.py`, `services/sandbox/python_runner.py`; `layla/tools/impl/system.py`. | Solid. |
| web_search | REAL | `layla/tools/impl/web.py`, `layla/tools/domains/web.py`; deps `duckduckgo-search` (req:53), `wikipedia` (req:54), `arxiv` (req:55), `trafilatura` (req:21). | Solid. |
| apply_patch | REAL | `unidiff>=0.7` (req:28); patch handling in `layla/tools/impl/code.py`, `services/file_checkpoints.py`. | Solid. |
| Tool tracing → DB | REAL | `core/executor.py:183-245` inserts into `tool_calls` table; surfaced via `routers/tools_history.py`. Tests in `tests/test_tool_tracing.py`. | Solid. |

### Tests

| Subsystem | Status | Evidence | Gap-to-vision |
|---|---|---|---|
| Test count by category | REAL | 151 test files under `agent/tests/`. Last run: 854 passed / 10 skipped / 43 deselected (`last_report.json:91`). | Solid. |
| Marker usage (endpoint/slow/e2e) | PARTIAL | Only 7 occurrences across 6 files of `@pytest.mark.(endpoint|slow|e2e)`. The 43 deselected tests imply marker-based deselection happens but coverage is thin. | Markers underused. |
| conftest isolation | REAL | `tests/conftest.py:13-36` forces `LAYLA_DATA_DIR` to a tmp dir, resets `_DB_PATH` + `_MIGRATED` flags before each session. `:39-60` resets `runtime_safety._config_cache` and `learnings._recent_learning_ts` per test. `agent/conftest.py:19-36` patches `python_compat` to a passing stub. | Watertight per the brief. |
| Mocking the thing under test | UNVERIFIED | Did not sample broadly enough to judge per-test mocking honesty. Visible: `tests/test_repo_indexer.py`, `tests/test_inference_router.py`, `tests/test_tool_tracing.py` exercise real code paths against real SQLite. | Sample looks real, not exhaustively verified. |

---

## Existing docs vs reality

| Doc | Claim | Reality |
|---|---|---|
| `SYSTEM_PLAN.md` (24,980 bytes, Apr 29) | "next thing to build is Phase A (Memory Coherence)" with canonical entity schema + memory router | Entity schema exists (`agent/schemas/entity.py`), memory router exists but is voluntary — most writers bypass. Phase A "done" status is overstated. |
| `ROADMAP.md` (17,547 bytes, Apr 29) | Phases 1.0 → 1.3 staged through weeks 7-22 | Phase 0/1/6 broadly delivered; Phases 11-14 entirely absent (no `layla/codex`, `layla/ingestion`, `layla/scheduler`, Prometheus/structlog). |
| `ARCHITECTURE.md` (47,188 bytes, Apr 17) | UNVERIFIED — file size suggests detailed map; not read in this pass | Mark as UNVERIFIED. |
| `LAYLA_NORTH_STAR.md` (8,183 bytes, Apr 27) | 6-aspect debate, sovereignty, idle-aware | Aspects real; debate absent; sovereignty real (no outbound cloud); idle-aware = coarse process-skip only. |
| `PROJECT_BRAIN.md`, `AGENTS.md`, `IMPLEMENTATION_STATUS.md` | UNVERIFIED — not read | Mark as UNVERIFIED. |
| `agent/docs/IMPLEMENTATION_STATUS.md`, `agent/docs/FULL_TECHNICAL_AUDIT.md`, `agent/docs/SYSTEM_COHERENCE_SCORECARD.md` | All exist | UNVERIFIED — overlapping doc tree probably contains stale claims. The audit subdirectory (this file's parent) is new. |
| `agent/scripts/last_report.json` | `confidence_pct: 100` | Cosmetic — masks `real_assertions_pass: 1/3` (repo_index empty, config_cache not importable). |

---

## Top 20 highest-leverage gaps (ranked by impact ÷ effort)

1. **Enforce memory router as the only write path.** Add a lint check to `scripts/check_wiring.py` that **fails** if any module other than `services/memory_router.py` imports `layla.memory.db.save_learning` / `save_aspect_memory`. Then migrate the ~33 bypassers (mechanical). Unlocks Phase 11 coherence. Effort: 4-8 h. Impact: enormous.
2. **Restore `original_goal` preservation through `autonomous_run`.** `agent_loop.py:3078` already captures `goal_original`; thread it into reflection/learning/memory writes as the canonical text instead of the optimised rewrite. Effort: 2 h. Impact: solves "memory contamination by optimiser" silently degrading user-recall fidelity.
3. **Fix the `repo_index_populated=false` signal.** Either (a) make `scripts/check_repo_index.py` accept "no sandbox_root configured" as N/A, or (b) seed a default workspace at first-run so the index actually populates. Effort: 1 h. Impact: real_assertions goes 1/3 → 2/3 with no behaviour change.
4. **Fix `config_cache_importable=false`.** `scripts/check_wiring.py` and `last_report.json` both flag this; means `services/config_cache.py` either doesn't exist or fails import on the check runner. Most subsystems delegate to it (`memory_router.py:60-64`, `airllm_runner.py:50-55`). If it's missing, every `_cfg()` is silently falling back to `{}`. Effort: 1 h. Impact: huge — runtime config might be dead. **Investigate first.**
5. **Add a real debate/council mode.** Even minimal: `aspect_mode = solo | debate(2-aspect) | council(3-aspect)`; have the loop call the LLM twice with different system prompts and synthesise. Effort: 6-12 h. Impact: closes the biggest north-star gap.
6. **Add `prometheus_client` + `services/metrics.py` + `/metrics` route.** Phase 13. Hot-path counters for tool calls, LLM latency, memory ops. Effort: 4-6 h. Impact: turns observability from anecdotal to instrumented.
7. **Add structlog (or a JSON formatter onto `task_context.install_filter`).** Half the work is already done. Effort: 2 h. Impact: incident-debuggable logs.
8. **Carve `services/idle_scheduler.py` out of `main.py`.** Move job registration + activity gate + game-detect into one module under `layla/scheduler/jobs.py`. Effort: 3 h. Impact: shrinks `main.py` from 1089 lines, makes the scheduler testable.
9. **Code-split `ui/js/layla-app.js`.** It's 4024 lines / >150 KB. Plan target is ≤176 KB total, this single file is most of that. Effort: 6-10 h. Impact: TTI + perf.
10. **Move `airllm` and `llmlingua` either into `requirements.txt` as optional extras (`[airllm]`, `[compression]`) or explicitly drop the claim from `SYSTEM_PLAN.md`.** Today the README/plan over-promises. Effort: 1 h. Impact: honesty + reproducibility.
11. **Implement `layla/codex/` (Person/Project/Concept/Event/Skill).** Schemas already exist (`agent/schemas/entity.py`); just need the CRUD module + linker. Effort: 8-12 h. Impact: Phase 11 unlock.
12. **Implement `layla/ingestion/` (PDF/audio/web → entities).** Pieces exist (`services/doc_ingestion.py`, `services/stt.py`, `trafilatura`); wrap them into a single pipeline + `routers/ingest.py`. Effort: 8 h. Impact: Phase 12 unlock.
13. **Add the inverse-wiring lint check (no direct writes outside router).** Same as #1 but framed as ongoing CI. Effort: small once #1 lands.
14. **Aspect-keyed model routing.** `services/model_router.py` should accept `aspect_id` and consult a per-aspect override table (config). Effort: 3 h. Impact: differentiates aspects in inference, not just voice.
15. **Stale-doc sweep.** `agent/docs/` is 80+ markdown files, many overlapping (`AUDIT_2025-03-14.md`, `AUDIT_OPENCLAW_CORE_EMULATION.md`, `MODULE_SWEEP_*`, `*_SECOND_SWEEP.md`). Decide which are canonical; archive the rest under `docs/archive/`. Effort: 2-3 h. Impact: reduces collaborator confusion.
16. **Add `services/expert_routing.py` (per-task model assignment).** Plan Phase 4.1 calls for it. Effort: 4 h.
17. **Reranker layer.** Either `sentence-transformers/cross-encoder/ms-marco-MiniLM-L-12-v2` or a small LLM rerank pass for retrieval. Effort: 3-4 h. Impact: retrieval quality.
18. **Multi-node networking (Syncthing or self-hosted)** — promote `services/syncthing_sync.py` from scaffold to at least one production importer (e.g. nightly auto-rescan job in `main.py`). Effort: 2 h. Impact: closes the "scalable phone → datacenter" axis (currently 0%).
19. **`agent/.layla/` vault structure.** Currently has `layla.db`, `plan_store/`, `project_memory.json`, `repo_index.db` — no markdown vault. Add an `agent/.layla/vault/` markdown mirror that pairs with `obsidian_sync`. Effort: 4 h. Impact: north-star "memory-driven growth via Obsidian-shaped vault without Obsidian dependency".
20. **Fix `confidence_pct` calculation in `run_all_checks.py`.** It currently reports 100% while real_assertions = 1/3. Weight real_assertions ≥ 50% of the score. Effort: 30 min. Impact: trustworthy CI signal.

---

## Subsystems discovered but not in original list

- **`services/coordinator.py`** — appears in 7 importers; coordinates plan execution. STATUS: REAL. Worth documenting.
- **`services/engineering_pipeline.py`** — wired into `agent_loop.py` via `engineering_pipeline_mode` (lines 3070, 3185). STATUS: REAL.
- **`services/cognitive_workspace.py`** + **`services/workspace_awareness.py`** + **`services/workspace_index.py`** — three overlapping concerns. STATUS: REAL but candidate for consolidation.
- **`services/agent_task_runner.py`** + `routers/agent_tasks.py` (mounted at `main.py:845`) — background task resume. STATUS: REAL.
- **`services/initiative_engine.py`** — proactive project proposals, gated by `initiative_project_proposals_enabled` + trust tier (`main.py:420-433`). STATUS: REAL but default off.
- **`services/curiosity_engine.py`** — surfaces suggestions to save as `kind=curiosity` learnings every 60 min (`main.py:550-560`). STATUS: REAL.
- **`services/maturity_engine.py`** — trust-tier + maturity-phase logic. STATUS: REAL.
- **`services/experience_replay.py`**, **`services/knowledge_distiller.py`**, **`services/memory_consolidation.py`** — background intelligence trio scheduled on intervals. STATUS: REAL.
- **`services/german_mode.py`** + `routers/german.py` — language-learning mode (item #10 in plan). STATUS: REAL but tangential to north-star.
- **`agent/fabrication_assist/`** + several `tests/test_fabrication_assist*.py` — CAD/CAM fabrication helper. STATUS: REAL but domain-specific.
- **`agent/cursor-layla-mcp/`** (repo root) + `agent/services/mcp_client.py` — MCP integration. STATUS: REAL.
- **`agent/skills/`** + `layla/skills/registry.py` + `services/markdown_skills.py` — skill packs system. STATUS: REAL.
- **`services/sandbox/python_runner.py`** + `services/sandbox/shell_runner.py` — sandboxed code execution. STATUS: REAL.
- **`agent/discord_bot/`** (repo root) — Discord integration. STATUS: UNVERIFIED, separate from agent loop.
- **`services/worker_pool.py`** + `services/worker_cgroup_linux.py` + `services/worker_os_limits.py` — resource limits for sandboxed workers. STATUS: REAL.
- **`services/research_report.py`** + `routers/research.py` + the `research_*.py` collection in `agent/` root — research pipeline. STATUS: REAL.

---

## Recommended next-phase order

Given the audit, the productive sequence for Phases B-F is:

### Phase B: Truth-telling repair (1 week)
Do **before** any new feature work.
- Items #4 (config_cache), #3 (repo_index signal), #20 (real_assertions weighting) from the gap list. Fixes the meta — your CI is currently lying to you.
- Item #15 (stale-doc sweep): archive the half-rotted `agent/docs/` tree so the next phase isn't reading lies.

### Phase C: Memory coherence — the real Phase A (1-2 weeks)
- Items #1 + #13 (enforce router) + #2 (preserve original_goal) + #11 (`layla/codex/`).
- This is the plan's "Phase A" but it isn't actually done. Finish it before stacking new memory infrastructure.

### Phase D: Aspect engine — close the north-star gap (1-2 weeks)
- Item #5 (debate/council) + #14 (aspect-keyed model routing).
- Without this, the north-star claim is fiction. Everything else can wait.

### Phase E: Observability + scheduler factoring (1 week)
- Items #6, #7, #8 (Prometheus + structlog + extract scheduler).
- Sets up Phase 13/14 of the plan without the full Grafana stack yet.

### Phase F: Ingestion + reranker + vault (2 weeks)
- Items #12 (`layla/ingestion/`), #17 (reranker), #19 (`.layla/vault/`).
- These compound on the now-coherent memory.

**Defer:**
- AirLLM, KB-builder STORM/GraphRAG (item #10 — either officialise as optional extras or drop the claim; do not promote until #1-12 land).
- Multi-node mesh / WireGuard / mDNS — depends on Syncthing being live first (item #18 small step).
- UI code-split (item #9) — important but cosmetic relative to coherence work; do in Phase E or F's downtime.

The unifying principle: **stop adding rooms to the house until the load-bearing walls (memory router enforcement, original_goal preservation, debate engine) are real.** The audit's high-confidence percentage hides that those walls are voluntary today.
