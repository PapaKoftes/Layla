# LAYLA: COHESION REPORT — STABILIZE OR TRIM

> **Source:** 13 deep-dive design documents, each auditing a major subsystem from  
> architecture, stability, security, and testing perspectives.  
> **Date:** 2026-05-17  
> **Verdict:** The core is strong. The periphery is bloated. Cut the dead wood,  
> harden the fragile, finish or kill the incomplete.

---

## EXECUTIVE SUMMARY

| Rating | Count | Action |
|--------|-------|--------|
| **STABLE** | 163 components | Lock in. Don't touch unless adding tests. |
| **FRAGILE** | 29 components | Harden. These work but will break under pressure. |
| **INCOMPLETE** | 22 components | Finish or kill. Half-built is worse than missing. |
| **DEAD** | 14 components | **Delete.** Dead code is tech debt that confuses and misleads. |

**Bottom line:** ~72% of the project is production-solid. The remaining ~28% is a mix
of half-finished experiments, dead stubs, and fragile code that needs either hardening
or removal. This report is the definitive hit list.

---

## PART 1: EVERYTHING TO DELETE (DEAD CODE — TRIM THE FAT)

These components exist in the codebase but are **never called, never reachable, or
fundamentally broken**. They add confusion, slow down grep/search, and create false
impressions of capability. **Delete all of them.**

### 1.1 Dead Code — Files & Functions

| Component | Location | Why It's Dead | Action |
|-----------|----------|---------------|--------|
| `_PHATIC_QUICK_PATTERNS` | `agent_loop.py` | Defined but never referenced. Quick-reply uses `_quick_reply_for_trivial_turn()` instead. | Delete the constant |
| `_reflect_on_response()` | `agent_loop.py` | Duplicates completion gate. Only reachable in stream_reason path. Adds unnecessary LLM call. | Delete the function |
| `classify_intent()` | `agent_loop.py` | Legacy heuristic. Only fallback when `_llm_decision()` returns None — which almost never happens with 3-strategy extraction. | Delete the function |
| `run_subagents()` | `autonomous/subagents.py` | Always returns `subagents_not_enabled`. Zero callers. Entire file is a stub. | Delete the file |
| `_airllm_warmup_job()` | `layla/scheduler/jobs.py` | Defined but never imported into `registry.py`. Never runs. | Delete the function |
| `_syncthing_rescan_job()` | `layla/scheduler/jobs.py` | Defined but never imported into `registry.py`. Never runs. | Delete the function |
| `run_all_jobs()` | `services/background_intelligence.py` | Never called. The 3 functions it orchestrates (`run_codex_relationship_discovery`, `run_spaced_repetition_review`, `run_kb_synthesis_check`) are only reachable through it. | Delete `run_all_jobs` and its 3 orphan functions |
| `apply_decay_if_needed()` | `layla/memory/capabilities.py` | Exists but never called. Capabilities grow but never shrink. | Delete or wire in (see Incomplete section) |
| `compute_runtime_caps()` | `services/pre_loop_setup.py:211-276` | Never called. Inlined in agent_loop.py. | Delete the function |
| `install-autostart.ps1` | Repo root | References wrong venv path (`venv/` vs `.venv/`). Uses legacy "Jinx" naming. Non-functional. | Delete the file |
| `start-layla-server.ps1` | Repo root | Same venv path bug. Only 2 lines. Non-functional without manual intervention. | Delete the file |
| Voice evolution system | `personalities/*.json` | Phase name mismatch: maturity uses `awakening/attunement/resonance/sovereignty/transcendence` but voice_evolution keys use `nascent/apprentice/adept/veteran/transcendent`. **Feature is completely non-functional at runtime.** | Fix the key names or delete voice_evolution |
| `blend_weight` field | `personalities/*.json` | Field exists on all 6 personalities. Value is always 0. No blending system exists. | Delete the field from all JSONs |
| `learnings_archive` table | `layla/memory/migrations.py` | Table created in migration. No production code reads or writes it. | Remove from migration |
| `golden_examples` table | `layla/memory/migrations.py` | Table created in migration. No domain module uses it. | Remove from migration |

### 1.2 Duplicate Code — Pick One, Delete the Other

| Duplicate Pair | Location | Issue | Action |
|----------------|----------|-------|--------|
| `skills.py` / `markdown_skills.py` | `agent/services/` | **Identical files.** Risk of silent divergence if one is edited. | Keep `skills.py`, delete `markdown_skills.py`, update imports |
| `observability.py` / `telemetry.py` | `agent/services/` | **Identical files.** Same risk. | Keep `observability.py`, delete `telemetry.py`, update imports |
| `first_run.py` / `installer_cli.py` / `run_first_time.py` | `agent/` and `agent/install/` | Three overlapping setup code paths with duplicate model-selection logic. | Consolidate into `installer_cli.py` as single entry point |
| `Download-Model.ps1` / `model_downloader.py` | Root / `agent/install/` | Separate code path with no resume, no verification, hardcoded URLs. | Delete `Download-Model.ps1`, use `installer_cli.py download` |
| Three chunking implementations | `chunker.py`, `vector_store.py`, `workspace_index.py` | Three different chunking strategies (512 tokens, 600 chars, tree-sitter) with no shared interface. | Consolidate into `chunker.py` with strategy parameter |
| Three graph systems | `codex_db`, `memory_graph.py`, `personal_knowledge_graph.py` | Three disconnected graph implementations (SQLite, NetworkX/GraphML, in-memory). No shared schema. | Unify under `memory_graph.py` with pluggable backends |
| Two HTTP CAD bridges | `http_cad_bridge.py`, `gencad_generate_toolpath` | Two inconsistent integration points posting to the same URL with different libraries (urllib vs httpx) and different payload schemas. | Consolidate into `http_cad_bridge.py` |

---

## PART 2: EVERYTHING TO STABILIZE (FRAGILE — HARDEN OR IT BREAKS)

These components work today but have structural weaknesses that will cause failures
under load, edge cases, or maintenance.

### 2.1 Critical — Fix Before Any Deployment

| Component | Location | Issue | Fix |
|-----------|----------|-------|-----|
| **Sandbox fallback to `Path.home()`** | `layla/tools/sandbox_core.py` | On config error, `_get_sandbox()` falls to home dir, effectively disabling sandbox containment. | Fail hard with RuntimeError instead of falling back. |
| **`_autonomous_run_impl_core()` — 1,664 lines** | `agent_loop.py` | Single function. Impossible to test, debug, or reason about. 120+ try/except blocks. | Extract into 6-8 functions: prompt_build, decision, dispatch, post_check, memory, response. |
| **Silent exception swallowing (134 sites)** | `agent_loop.py`, `core/executor.py` | Most `except Exception` blocks log at DEBUG or do nothing. Critical failures go unnoticed. | Triage: safety-critical → `logger.error(exc_info=True)`, functional → `logger.warning`, cosmetic → `logger.debug(exc_info=True)` |
| **Approval file race condition** | `services/tool_dispatch.py` | `approvals.json` and `execution_log.json` read/written without file locking. Concurrent requests corrupt data. | Add `file_lock.py` usage (already exists in codebase). |
| **Shell approval variable naming inversion** | `services/tool_dispatch.py` | `_need_shell_approval` assigned from `is_tool_allowed` which returns True when approved — inverted logic. | Rename or invert the boolean. |
| **`search_codebase` unreachable** | `services/tool_dispatch.py` | Listed in `_HARDCODED_INTENTS` but has no handler entry. Silently skipped by both dispatch paths. | Add handler or remove from intents list. |
| **BM25 capped at 2000 learnings** | `services/retrieval.py` | BM25 corpus rebuilt on every call but only from first 2000 learnings. Beyond that, BM25 results degrade silently. | Persist BM25 index, rebuild incrementally. |

### 2.2 High Priority — Fix Soon

| Component | Location | Issue | Fix |
|-----------|----------|-------|-----|
| **Tool dispatch boilerplate** | `services/tool_dispatch.py` | write_file, run_python, apply_patch handlers each repeat 30-40 lines of identical boilerplate. `_base_tool_handler` exists but isn't universally used. | Migrate all handlers to use `_base_tool_handler`. |
| **`_llm_decision()` — 380 lines** | `agent_loop.py` | Mixes prompt construction, model routing, 3 extraction strategies, and cleanup in one function. | Extract into `services/llm_decision.py` with strategy classes. |
| **4-layer tool filtering** | `agent_loop.py` | Policy → deterministic route → toolchain graph → visibility cap, with fallback-on-failure at each layer. Hard to reason about which tools survive. | Document the filter chain. Add logging of tools eliminated at each stage. |
| **Output sanitization regex loop** | `agent_loop.py:3730-3783` | 50+ lines of regex-based echo stripping with a loop-of-20. Edge cases likely. | Extract to utility function. Add tests for known edge cases. |
| **Memory graph — no write locking** | `layla/memory/memory_graph.py` | File-based GraphML persistence with no concurrent write protection. | Add threading.Lock around save operations. |
| **NSFW triggers too broad** | `personalities/lilith.json` | Triggers like "let go" and "be free" can fire in non-NSFW contexts. Keyword matching only, no semantic understanding. | Add a minimum trigger count or context check before activating NSFW mode. |
| **Repeated config loads** | `agent_loop.py` | `runtime_safety.load_config()` called 8+ times within `_autonomous_run_impl_core()`. Config is cached with TTL, but the redundancy is wasteful and confusing. | Load once at function entry, pass dict down. |
| **Elasticsearch bridge** | `services/elasticsearch_bridge.py` | No connection pooling, no index management, no bulk operations. | Add connection reuse via module-level client. |
| **Tool args validation — 4% coverage** | `services/tool_args.py` | Only 6 of ~167 tools have validation schemas. | Add schemas for DANGEROUS_TOOLS first (write_file, shell, run_python). |
| **6 polling timers in UI** | `agent/ui/js/*.js` | 6 concurrent setInterval timers. No pause on tab hidden. | Add `visibilitychange` listener to pause/resume all polling. |

### 2.3 Medium Priority — Fix When Touching

| Component | Location | Issue |
|-----------|----------|-------|
| OpenScad backend | `geometry/backends/openscad_backend.py` | Depends on external CLI. No SCAD validation. Platform-dependent. |
| HTTP CAD bridge | `geometry/bridges/http_cad_bridge.py` | Informal protocol. Two inconsistent integration points. |
| Cognitive workspace | `services/cognitive_workspace.py` | Depends on LLM producing parseable JSON. No validation beyond regex. |
| Structured gen | `services/structured_gen.py` | Must handle multiple outlines API versions via try/except chains. |
| Initiative inline | `services/initiative_inline.py` | Complex 6-tier fallback logic. Config-gated off by default. |
| Background intelligence | `services/background_intelligence.py` | 3 of 5 functions orphaned. Only 2 are live. |
| Bulk ingest | `scripts/bulk_ingest.py` | Duration calculation bug. No progress reporting. No error recovery. |
| Code intelligence | `services/code_intelligence.py` | Thin facade coupled to `workspace_index._workspace_graph` global. |
| Personal knowledge graph | `services/personal_knowledge_graph.py` | Ephemeral in-memory. No persistence. Naive keyword matching. |
| Graph learning | `services/graph_learning.py` | Silent `except Exception: pass` on save. Duplicate entity extraction. |
| Remote rate limiter | `services/remote_rate_limit.py` | Breaks under multi-worker deployments. No external store. |
| Aspect selection (embedding) | `services/aspect_behavior.py` | 0.35 cosine threshold untested. |
| Title system | `services/character_creator.py` | Titles are rank-gated but conditions ("100 code fixes") have no tracking. |
| Research router | `routers/research.py` | Raw dict inputs. No workspace sandbox check. No timeout config. |
| System router | `routers/system.py` | 40+ endpoints — kitchen sink. Should be split. |

---

## PART 3: EVERYTHING TO FINISH (INCOMPLETE — COMPLETE OR KILL)

These are half-built features. Each one creates confusion about what Layla can
actually do. **Decision needed on each: finish it or delete it.**

### 3.1 Finish — High Value If Completed

| Component | Location | What's Missing | Effort |
|-----------|----------|----------------|--------|
| **Capability decay** | `layla/memory/capabilities.py` | `apply_decay_if_needed()` exists but is never called. Without it, capabilities only grow, never decay. The growth model is one-directional. | 1h — wire into scheduler as periodic job |
| **Experience replay** | `services/experience_replay.py` | Read-only analysis. Computes patterns but never persists heuristic updates. The RL loop is open. | 4h — add heuristic persistence and feedback loop |
| **Extractors** | `layla/ingestion/extractors.py` | Missing XLSX, PPTX, OCR, Jupyter notebook support. | 4h — add openpyxl, python-pptx (both in deps), nbformat extractors |
| **Voice evolution** | `personalities/*.json` | Phase key name mismatch kills the feature. Easy fix. | 1h — rename keys to match maturity phases |
| **Tool args validation** | `services/tool_args.py` | 4% coverage. Only 6 tools validated. | 8h — add schemas for all DANGEROUS_TOOLS (write_file, shell, run_python, apply_patch, git_commit) |
| **Resource-aware chunking** | `agent_loop.py` | Creates checkpoint on high load but no resume mechanism. | 3h — add checkpoint resume at loop entry |
| **Auto updater** | `services/auto_updater.py` | No rollback, no restart, no non-git update path. | 4h — add git stash backup before pull, subprocess restart |

### 3.2 Kill — Low Value, Not Worth Finishing

| Component | Location | Why Kill It | Effort Saved |
|-----------|----------|-------------|-------------|
| **AirLLM runner** | `services/airllm_runner.py` | Functional but not integrated into inference pipeline. Manual GPU memory management. Layer-by-layer inference is a niche use case covered by llama.cpp offloading. | Skip maintenance of an unused module |
| **Qdrant adapter** | `layla/memory/vector_qdrant.py` | 7 functions but not integrated into retrieval pipeline. ChromaDB is the primary and only tested path. Maintaining two vector backends doubles testing surface. | Skip testing/maintaining alternative backend |
| **Codex semantic** | `services/codex_semantic.py` | Token overlap only. No actual vector similarity despite the name. Gated off by default (`codex_semantic_enabled: false`). | Remove misleading module |
| **Agent roles** | `services/agent_roles.py` | Minimal implementation. Module name overpromises. Only useful in deep reasoning mode. Overlaps with aspect system. | Remove overlap with aspect system |
| **Style profile injection** | `services/style_profile.py` | Extraction works but injection into prompts is unclear. Feedback loop may not be closed. | Either wire into system_head_builder or remove |
| **Agents router (blackboard)** | `routers/agents.py` | Spawn works but blackboard feature appears unfinished. No lifecycle management. | Remove blackboard, keep spawn |
| **Skill discovery** | `services/skill_discovery.py` | Explicitly a stub. No persistence, no real analysis, hardcoded keyword matching. | Delete until real implementation needed |
| **OpenTelemetry export** | `services/otel_export.py` | Context manager exists but no tracer/exporter configuration. Needs full OTel setup to function. | Delete until infra exists for OTel |
| **Langfuse export** | `services/langfuse_export.py` | Single span type, no trace context, no generation tracking. Minimal value. | Delete until proper Langfuse integration needed |
| **Auto setup** | `services/auto_setup.py` | Minimal functionality. Mostly placeholder for future hooks. | Delete, use installer_cli.py instead |
| **Release workflow** | `.github/workflows/release.yml` | References `installer/build_installer.ps1` which may not exist. No Linux/macOS artifacts. | Fix or remove from CI |
| `codex_discoveries` table | `layla/memory/migrations.py` | Created in migration, no CRUD module found. | Remove from migration |
| `journal_entity_links` table | `layla/memory/migrations.py` | Created in migration, no CRUD module found. | Remove from migration |

---

## PART 4: CROSS-CUTTING CONCERNS

Issues that span multiple subsystems and need coordinated fixes.

### 4.1 Missing Indexes (from Memory doc)

```sql
CREATE INDEX IF NOT EXISTS idx_learnings_embedding_id ON learnings(embedding_id);
CREATE INDEX IF NOT EXISTS idx_learnings_content_hash ON learnings(content_hash);
CREATE INDEX IF NOT EXISTS idx_conversation_messages_conversation_id ON conversation_messages(conversation_id);
CREATE INDEX IF NOT EXISTS idx_relationships_from ON relationships(from_entity);
CREATE INDEX IF NOT EXISTS idx_relationships_to ON relationships(to_entity);
CREATE INDEX IF NOT EXISTS idx_goal_progress_goal_id ON goal_progress(goal_id);
CREATE INDEX IF NOT EXISTS idx_episode_events_episode_id ON episode_events(episode_id);
```

### 4.2 Missing Foreign Keys

15 foreign key relationships are documented but not enforced. `PRAGMA foreign_keys=ON`
is not set. Orphan records accumulate silently.

### 4.3 Tables Without Retention Policies

17 tables have no cleanup job. Over months/years of operation, these will grow
unbounded:
- `entities`, `relationships`, `episodes`, `episode_events`
- `goals`, `goal_progress`, `capabilities`, `capability_events`
- `improvements`, `plans`, `plan_steps`
- `codex_entities`, `codex_relationships`
- `study_plans`, `study_sessions`
- `audit` (execution log)
- `model_outcomes`

### 4.4 Config Gates Always Off

6 features are config-gated and default to `false`, meaning they're effectively dormant:
- `initiative_project_proposals_enabled`
- `initiative_engine_enabled`
- `inline_initiative_enabled`
- `autonomy_optimizer_enabled`
- `scheduler_use_capabilities`
- `enable_lens_refresh`

**Decision needed:** Enable by default, or delete the code behind the gate.

### 4.5 Input Validation Coverage

- **API endpoints:** Only ~25% of POST endpoints use Pydantic models. The rest parse raw dicts.
- **Tool arguments:** Only 4% of tools have validation schemas.
- **Error responses:** 4 co-existing error response shapes across routers. No standard.

### 4.6 Error Handling Debt

- **134 bare `except Exception` blocks** across agent_loop.py and executor.py
- **Silent `except: pass`** in RL preference updates and graph learning
- **120+ try/except in one function** (`_autonomous_run_impl_core`)
- **Audit logging silently stops** if exception occurs during audit write

---

## PART 5: PRIORITY EXECUTION ORDER

### Tier 0: Delete Dead Code (2-4h)
*Instant cleanup. No functional change. Reduces confusion.*

1. Delete 3 dead functions from `agent_loop.py`
2. Delete `autonomous/subagents.py`
3. Delete 2 dead scheduler jobs from `jobs.py`
4. Delete `run_all_jobs()` + 3 orphan functions from `background_intelligence.py`
5. Delete `install-autostart.ps1` and `start-layla-server.ps1`
6. Delete `Download-Model.ps1`
7. Remove `learnings_archive`, `golden_examples`, `codex_discoveries`, `journal_entity_links` from migrations
8. Remove `blend_weight` from all personality JSONs
9. Deduplicate `skills.py`/`markdown_skills.py`
10. Deduplicate `observability.py`/`telemetry.py`

### Tier 1: Fix Critical Safety Issues (4-6h)
*These are actual bugs that could cause data loss or security issues.*

1. Fix sandbox `Path.home()` fallback → fail hard with RuntimeError
2. Fix shell approval variable naming inversion
3. Fix approval file race condition (add file locking)
4. Fix voice evolution phase key mismatch
5. Add `PRAGMA foreign_keys=ON` to db_connection.py
6. Add orphan record cleanup to migrations

### Tier 2: Harden Core Loop (8-12h)
*The agent loop is the heart. It must be solid.*

1. Extract `_autonomous_run_impl_core()` into 6-8 functions
2. Extract `_llm_decision()` into `services/llm_decision.py`
3. Triage 134 `except Exception` blocks (error/warning/debug)
4. Load config once at function entry, pass down
5. Add missing indexes to migrations

### Tier 3: Kill Low-Value Incomplete Code (2-3h)
*Remove half-built features that aren't worth finishing.*

1. Delete `airllm_runner.py` (or move to contrib/)
2. Delete `vector_qdrant.py` (or move to contrib/)
3. Delete `codex_semantic.py`
4. Delete `agent_roles.py`
5. Delete `skill_discovery.py`
6. Delete `otel_export.py` and `langfuse_export.py`
7. Delete `auto_setup.py`
8. Clean up `agents.py` blackboard code

### Tier 4: Finish High-Value Incomplete Code (12-16h)
*These features are close to working and provide real value.*

1. Wire `apply_decay_if_needed` into scheduler (1h)
2. Fix voice evolution key names (1h)
3. Add XLSX/PPTX/notebook extractors (4h)
4. Add tool args validation for DANGEROUS_TOOLS (8h)
5. Consolidate 3 setup code paths into `installer_cli.py` (4h)

### Tier 5: Reduce Duplication (8-12h)
*Lower priority but improves maintainability.*

1. Consolidate 3 chunking implementations
2. Unify 3 graph systems under shared interface
3. Merge 2 HTTP CAD bridge implementations
4. Migrate all tool handlers to `_base_tool_handler`
5. Standardize API error response shape

---

## PART 6: SCORECARD

### Before Cleanup

```
Total components audited:  228
STABLE:                    163  (71.5%)
FRAGILE:                    29  (12.7%)
INCOMPLETE:                 22  ( 9.6%)
DEAD:                       14  ( 6.1%)

Code health:               C+
Deployment readiness:       58%
```

### After Tier 0-3 (delete + fix critical + harden + kill)

```
Total components:          ~200  (28 removed)
STABLE:                    ~178  (89%)
FRAGILE:                    ~15  ( 7.5%)
INCOMPLETE:                  ~7  ( 3.5%)
DEAD:                         0  ( 0%)

Code health:               B+
Deployment readiness:       75%
```

### After All 5 Tiers

```
Total components:          ~200
STABLE:                    ~190  (95%)
FRAGILE:                     ~7  ( 3.5%)
INCOMPLETE:                  ~3  ( 1.5%)
DEAD:                         0  ( 0%)

Code health:               A-
Deployment readiness:       85%
```

---

## DOCUMENT INDEX

All design documents are in `docs/design/`:

| # | Document | Focus |
|---|----------|-------|
| 00 | **This file** | Cohesion report: stabilize or trim |
| 01 | `01-core-agent-loop.md` | Main loop, decision cycle, state management |
| 02 | `02-memory-and-knowledge.md` | 52 tables, vector store, retention, migration |
| 03 | `03-llm-and-reasoning.md` | 4 backends, model routing, caching, output processing |
| 04 | `04-tools-safety-governance.md` | 167 tools, sandbox, dignity engine, approvals |
| 05 | `05-scheduler-background-growth.md` | 13+ jobs, idle detection, growth, self-improvement |
| 06 | `06-autonomous-and-research.md` | Controller, planner, 15-stage research pipeline |
| 07 | `07-api-surface-routers.md` | 265 endpoints, auth, WebSocket, validation |
| 08 | `08-ui-frontend.md` | 28 JS modules, state, PWA, security, performance |
| 09 | `09-personality-aspects-ethics.md` | 6 aspects, dignity engine, voice evolution, ethics |
| 10 | `10-data-ingestion-codex.md` | Pipeline, extractors, chunking, graphs, retrieval |
| 11 | `11-installation-deployment.md` | Install, first run, CI/CD, health checks |
| 12 | `12-networking-integrations.md` | Tailscale, mDNS, tunnel, plugins, Discord |
| 13 | `13-geometry-cad-cam.md` | 4 CAD backends, CAM, machining IR, fabrication |

---

*This report is the single source of truth for what to keep, what to fix, and what to cut.
Start with Tier 0 (delete dead code) — it's free improvement with zero risk.*
