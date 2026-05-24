# 05 -- Scheduler, Background Intelligence & Growth

> Design document for the subsystem that governs periodic background jobs,
> idle-time intelligence tasks, capability tracking, self-improvement proposals,
> experience replay, RL preference learning, and memory consolidation.

---

## 1. Scheduler Architecture

### 1.1 Library & Setup

The scheduler is built on **APScheduler `BackgroundScheduler`** with UTC
timezone.  All wiring lives in two files:

| File | Role |
|------|------|
| `agent/layla/scheduler/registry.py` | `create_scheduler(cfg)` -- builds the scheduler, registers every job, returns it **un-started** (caller invokes `.start()`). |
| `agent/layla/scheduler/jobs.py` | Pure job functions. Each uses lazy imports to avoid circular-import crashes at module load. |

`create_scheduler` receives the full `runtime_safety.load_config()` dict.
Interval values are clamped to sane bounds (`max()`/`min()` guards) and fall
back to defaults on `TypeError`/`ValueError`.

### 1.2 Instrumentation

`registry._instrumented(job_name, fn)` wraps job functions to record
Prometheus metrics via `services.metrics.record_scheduler_run(job_name, status)`
where `status` is `"ok"` or `"error"`.  Only a subset of jobs are wrapped
(mission_worker, nightly_backup, reindex_failed) -- the rest fire-and-forget
with bare `try/except` inside the job body.

### 1.3 Module-Level Singleton

`registry._scheduler` holds the single instance. `get_scheduler()` exposes it
for runtime introspection.  There is no mechanism to stop, replace, or
hot-reload jobs after creation.

---

## 2. Complete Job Roster

### 2.1 Always-Registered Jobs

These jobs are added unconditionally by `create_scheduler`:

| # | Job ID | Function | Default Interval | Config Key (interval) | What It Does |
|---|--------|----------|-------------------|-----------------------|--------------|
| 1 | `mission_worker` | `_mission_worker_job` | 2 min | `mission_worker_interval_minutes` (1--10) | Fetches one active mission from DB, executes its next step via `services.mission_manager.execute_next_step`. |
| 2 | `background_reflection` | `_bg_reflect` | 5 min | `background_reflection_interval_minutes` | Calls `background_intelligence.run_reflection_scan()` to find high-failure strategies in `strategy_stats`. |
| 3 | `background_codex` | `_bg_codex` | 10 min | `background_codex_update_interval_minutes` | Calls `background_intelligence.run_codex_entity_nudge()` to extract entities from recent conversation summaries and upsert them into the codex. |
| 4 | `background_memory_consolidation` | `_bg_memory` | 30 min (min 5) | `background_memory_consolidation_interval_minutes` | Calls `memory_consolidation.consolidate_periodic()` -- confidence decay import + distill tick. |
| 5 | `background_initiative` | `_bg_initiative` | 30 min (min 5) | `background_initiative_interval_minutes` | Generates LLM-based project proposals from project memory. Double-gated: `initiative_project_proposals_enabled` AND trust tier >= 2. |
| 6 | `background_memory_cleanup` | `_bg_cleanup` | 24 h | (none -- hardcoded) | Prunes low-confidence learnings (archives then deletes), applies retention policies, rotates audit log, cleans old research output files. |
| 7 | `nightly_db_backup` | `_bg_backup` | 24 h | (none -- hardcoded) | Hot-copies the SQLite database via `.backup()` API. Logs path, size, pruned count. |
| 8 | `repo_reindex` | `_bg_repo_reindex` | 30 min | (none -- hardcoded) | Re-indexes the workspace repo (requires `sandbox_root` in config). Marks degraded on failure. |
| 9 | `reindex_failed_learnings` | `_bg_reindex` | 30 min | (none -- hardcoded) | Re-embeds learnings whose ChromaDB dual-write previously failed. |

### 2.2 Conditionally-Registered Jobs

These are added only when `cfg.scheduler_study_enabled` is true (default: true):

| # | Job ID | Function | Default Interval | Config Key | What It Does |
|---|--------|----------|-------------------|------------|--------------|
| 10 | *(anonymous -- no id)* | `_scheduled_study_job` | 30 min (5--120) | `scheduler_interval_minutes` | Picks a study plan by urgency/diversification (capability-aware when `scheduler_use_capabilities` is true), runs autonomous study, records practice event. Skipped when gaming or no recent activity within `scheduler_recent_activity_minutes`. |
| 11 | `intelligence` | `_intelligence_job` | 60 min | (none -- hardcoded) | Three sub-tasks in sequence: knowledge distillation, experience replay, curiosity engine (saves up to 3 curiosity learnings). |
| 12 | `rl_preference_update` | `_rl_preference_job` | 30 min | (none -- hardcoded) | Recomputes tool preference scores from `tool_outcomes` + `capability_events`, persists to `rl_preferences` table. |

### 2.3 Lens Refresh (Separately Gated)

| # | Job ID | Function | Default Interval | Config Keys | What It Does |
|---|--------|----------|-------------------|-------------|--------------|
| 13 | *(anonymous)* | `rebuild_lens_knowledge` (from `lens_refresh`) | N days | `enable_lens_refresh` AND `lens_refresh_interval_days` | Rebuilds lens knowledge. Both config keys must be truthy. Default: off. |

### 2.4 Defined But Never Registered (Dead Jobs)

These functions exist in `jobs.py` but are **not imported or scheduled** by
`registry.py`:

| Function | Purpose | Status |
|----------|---------|--------|
| `_airllm_warmup_job` | Pre-load AirLLM model layers during idle. Checks `airllm_enabled` and idle state. | **DEAD** -- never imported into registry. |
| `_syncthing_rescan_job` | Trigger Syncthing folder rescan. Checks `syncthing_api_key`. | **DEAD** -- never imported into registry. |

---

## 3. Idle Detection

### 3.1 Module

`agent/layla/scheduler/idle_detector.py` -- stateful `IdleDetector` class +
module-level singleton.

### 3.2 Algorithm

Uses `psutil.cpu_percent(interval=0.5)` to sample CPU.  Three zones:

| CPU Range | Behavior |
|-----------|----------|
| `>= idle_active_cpu_threshold` (default 0.60) | **Active** -- resets idle timer. |
| `< idle_cpu_threshold` (default 0.30) | **Low** -- starts/continues idle timer.  Declared idle when timer exceeds `idle_timeout_minutes` (default 10 min). |
| Between thresholds | **Ambiguous** -- does not reset idle timer, does not declare idle. |

### 3.3 Config Keys

| Key | Type | Default | Effect |
|-----|------|---------|--------|
| `idle_detection_enabled` | bool | `true` | Master switch. When false, `is_idle()` always returns false. |
| `idle_cpu_threshold` | float | `0.30` | CPU fraction below which = "low". |
| `idle_active_cpu_threshold` | float | `0.60` | CPU fraction above which = "definitely active". |
| `idle_timeout_minutes` | int | `10` | Minutes of sustained low-CPU before idle is declared. |

### 3.4 Integration Points

- `_airllm_warmup_job` calls `check_idle()` to gate model pre-loading (but this job is never scheduled -- see section 2.4).
- `mark_user_active()` is exposed for message handlers to reset the timer.
- No currently-scheduled job uses `IdleDetector` as a gate.

### 3.5 Activity Window (Separate Module)

`agent/layla/scheduler/activity.py` provides a simpler mechanism:

- `record_activity()` -- called from API routes (`/agent`, `/wakeup`, etc.) to set `_last_activity_ts`.
- `is_active_window(max_idle_minutes)` -- true if last interaction was within the window.
- `is_game_running()` -- scans `psutil.process_iter` for known game processes (Overwatch, Valorant, Steam, etc.). Used by `_scheduled_study_job` to skip study when the operator is gaming.

The default `scheduler_recent_activity_minutes` is `1440` (24 hours), meaning study runs essentially any time the server is up.

---

## 4. Background Intelligence

### 4.1 Module

`agent/services/background_intelligence.py` -- five independent intelligence
functions, each non-destructive and best-effort.

### 4.2 Scheduled Functions

Only two are called from the scheduler:

| Function | Called By | What It Does |
|----------|-----------|--------------|
| `run_reflection_scan()` | `_bg_reflect` (every 5 min) | Queries `strategy_stats` for high-failure strategies (fail_count/total > 50% with >= 3 samples). Logs warnings. |
| `run_codex_entity_nudge()` | `_bg_codex` (every 10 min) | Reads 5 recent conversation summaries, extracts entities via `codex.enricher.extract_entities`, upserts new ones at confidence 0.35. Caps at 3 entities per summary. |

### 4.3 Orphaned Functions (Never Scheduled)

| Function | What It Does | Why Orphaned |
|----------|--------------|--------------|
| `run_codex_relationship_discovery()` | Finds entity co-occurrences in learnings, creates `co_occurs` relationships (capped at 10/run). | Only reachable via `run_all_jobs()` which is never called. |
| `run_spaced_repetition_review()` | Finds learnings with `next_review_at <= now`, bumps importance (simplified SM-2), schedules next review. | Same -- only in `run_all_jobs()`. |
| `run_kb_synthesis_check()` | Counts learnings per tag, flags topics with 8+ learnings as KB article candidates. Does NOT auto-build -- log-only. | Same. |
| `run_all_jobs()` | Runs all five functions in sequence with timing. | Never imported anywhere outside the module. |

### 4.4 Intelligence Job (Composite)

`_intelligence_job` (scheduled every 60 min) runs three sub-tasks:

1. **Knowledge Distillation** (`services.knowledge_distiller.run_periodic_distillation`) -- Compresses 25 recent learnings into higher-level insights using LLM (or rule-based fallback). Saves as `kind="strategy"` learnings.
2. **Experience Replay** (`services.experience_replay.run_experience_replay`) -- Reviews tool outcome patterns and recent reflections. Currently read-only: computes patterns but does not persist heuristic updates.
3. **Curiosity Engine** (`services.curiosity_engine.get_curiosity_suggestions`) -- Identifies knowledge gaps (missing learnings for project goals/domains, no study plans, no architecture index). Saves up to 3 suggestions as `kind="curiosity"` learnings via `memory_router.save_learning`.

---

## 5. Growth Systems (Capability Tracking)

### 5.1 Module

`agent/layla/memory/capabilities.py` -- the evolution layer that tracks Layla's
skill growth per domain.

### 5.2 Core Concepts

| Concept | Description |
|---------|-------------|
| **Domain** | A named skill area (e.g., `coding`, `research`, `writing`, `planning`). Stored in `capabilities` table. |
| **Level** | 0.0--1.0 competency score. Incremented on practice, decremented on decay. |
| **Confidence** | 0.0--1.0 certainty about the level assessment. |
| **Decay Risk** | 0.0--1.0 linear ramp. 0.0 at day 0, 1.0 at `DECAY_FULL_DAYS` (30 days) since last practice. |
| **Trend** | `improving` / `stable` / `weakening` / `stagnant`. Computed from last 3 `capability_events` net delta. `stagnant` if > 14 days since practice with > 0 practice count. |
| **Reinforcement Priority** | 0.0--1.0 urgency score: `0.4*(1-level) + 0.3*decay_risk + 0.2*(bad_trend) + 0.1*(not improving)`. Higher = more urgent to study. |
| **Usefulness Score** | 0.0--1.0 quality of a learning outcome. Heuristic: < 50 chars = 0.2, < 150 chars = 0.4, structured content = 0.7, else 0.5. |

### 5.3 Practice Recording

`record_practice(domain_id, ...)` is the central write path:

1. **Usefulness gating**: If `usefulness_score < 0.3` (USEFULNESS_THRESHOLD_LOW), delta is minimized to 0.005 and cross-domain propagation is disabled. This prevents low-quality learning from inflating scores.
2. **Effective deltas**: `delta_level * usefulness_score`, `delta_confidence * usefulness_score`.
3. **Capability event insert**: Records `event_type="practice"` with all deltas and scores.
4. **Capability update**: Recomputes level, confidence, trend, decay_risk, reinforcement_priority; updates the capability row.
5. **Maturity XP**: Awards 30 XP to the maturity engine (best-effort).
6. **Cross-domain propagation**: When `usefulness >= 0.3` and `propagate_cross_domain` is true, looks up `capability_dependencies` and inserts weighted `cross_signal` events into dependent domains. Cross-delta is capped at `min(0.01, weight * delta * usefulness)`.

### 5.4 Decay

`apply_decay_if_needed()` iterates all capabilities:
- Skips domains practiced within `DECAY_THRESHOLD_DAYS` (7 days).
- Inserts a `decay_tick` event with `delta_level=-0.01`.
- Updates trend: `stable` -> `weakening`, `weakening` stays, `stagnant` stays.
- Recalculates reinforcement_priority.

**Issue**: This function exists but is never called by the scheduler or any
periodic job. Decay is defined but not enforced.

### 5.5 Study Plan Selection

`get_next_plan_for_study(active_plans, use_capabilities, ...)`:

1. When `use_capabilities=False`: picks plan with oldest `last_studied`.
2. When `use_capabilities=True`:
   - Maps plans to domains (via explicit `domain_id` or `_topic_to_domain_map()` heuristic).
   - Computes urgency per plan: `0.5*reinforcement_priority + 0.3*decay_risk + 0.2*time_factor`.
   - **Anti-specialization**: domains with level > median + 0.3 get urgency multiplied by 0.7.
   - **Diversification**: skips domains that appeared >= `SCHEDULER_MAX_SAME_DOMAIN_IN_WINDOW` (2) times in the last `SCHEDULER_WINDOW_RUNS` (5) scheduler runs.
   - Falls back to highest-urgency if all are at max window count.

### 5.6 Learning Validation

`run_learning_validation(outcome_summary)` is a heuristic (no LLM call):
returns 0.2 for empty/short, 0.4 for brief, 0.7 for structured content with
bullets/numbers, 0.5 otherwise. Used by `_scheduled_study_job` to weight
practice recording.

---

## 6. Self-Improvement

### 6.1 Module

`agent/services/self_improvement.py` -- proposal generation and approval
workflow.

### 6.2 Proposal Generation

`generate_proposals(session_summary, capability_levels, recent_failures)`:
- **Deterministic, no LLM call.** Produces a fixed set of safe proposals.
- Always proposes: "Enable output quality gate".
- If recent failures exist: "Add regression test per failure class".
- If "performance" in session summary: "Add perf notes to plan reports".
- Persists each via `db.create_improvement()` with status `"pending"`.
- Capped at 6 proposals per invocation.

### 6.3 Approval Workflow

1. `list_proposals(status, limit)` -- queries `improvements` table.
2. `approve_batch(ids)` -- sets status to `"approved"`, then immediately calls `apply_approved_proposals(ids)`.
3. `apply_approved_proposals(ids)` -- for each approved proposal with `instructions.config_keys`, applies to `runtime_config.json` via a strict allowlist.
4. `reject(ids)` -- sets status to `"rejected"`.

### 6.4 Config Allowlist

Only these keys can be auto-applied:
- `output_quality_gate_enabled`
- `inline_initiative_enabled`
- `observation_mode_enabled`
- `capability_level_inject_enabled`
- `maturity_enabled`

Unknown keys are rejected with `error: "unknown_config_keys"`.

### 6.5 Safety Properties

- No LLM is involved in proposal generation (deterministic rules).
- Proposals cannot modify tool permissions, sandbox boundaries, or trust tiers.
- The operator must explicitly approve before any config change is applied.
- Config writes go through `runtime_safety.invalidate_config_cache()` to ensure
  hot-reload consistency.

---

## 7. Experience Replay

### 7.1 Module

`agent/services/experience_replay.py`

### 7.2 What Is Replayed

- **Tool Patterns**: Queries `db.get_tool_reliability()` for tools with >= 3 uses. Extracts success_rate, avg_latency, count.  Sorted by count descending, top 50.
- **Reflections**: Queries recent learnings, filters for content containing "Reflection", "Worked:", "Failed:", or "Improve:".  Top 10.

### 7.3 How It Works

`run_experience_replay()` returns a summary dict:
```
{tool_patterns: N, reflections_reviewed: N, top_reliable_tools: [...]}
```

This is **read-only** -- it computes patterns but does not update any planning
heuristics or weights.  The planner already queries `get_tool_reliability()`
directly at decision time.

### 7.4 RL Preference Updates

A separate module (`services/rl_feedback.py`) provides the actual feedback loop:

**Preference Score Formula**:
```
score = success_rate * 0.6
      + (1 - clamp(avg_latency_ms / 5000, 0, 1)) * 0.2
      + avg_usefulness * 0.2
```

**Hint Classification** (from `update_tool_preference_hints`):
| Condition | Hint |
|-----------|------|
| score > 0.8 AND samples >= 5 | `"preferred"` |
| score < 0.3 AND samples >= 5 | `"avoid"` |
| success_rate < 0.5 AND samples >= 3 | `"unreliable"` |
| otherwise | `""` (no hint) |

**Persistence**: `run_preference_update_job()` (every 30 min) writes computed
preferences to the `rl_preferences` table via `upsert_rl_preference`.

**Prompt Injection**: `get_rl_hint_for_prompt()` formats a "Tool Performance
Hints" block for the system prompt, listing preferred/avoid/unreliable tools.

**Feedback Recording**: `record_outcome_feedback(tool_name, success, latency_ms,
usefulness_score)` writes to `tool_outcomes` and optionally inserts a
`capability_event` with `event_type="tool_feedback"`.

---

## 8. Memory Consolidation

### 8.1 Module

`agent/services/memory_consolidation.py`

### 8.2 Post-Session Consolidation

`consolidate_session(conversation_id)`:
1. Loads up to 80 messages for the conversation.
2. Runs `distill.run_distill_after_outcome()` on a subset (4--12 messages).
3. If the last outcome evaluation was a failure, prunes low-confidence learnings (threshold 0.08, batch 5).
4. If >= 12 messages, flags `"thread_ready_for_summary"`.

### 8.3 Periodic Consolidation

`consolidate_periodic()` (called every 30 min by `_bg_memory`):
1. Imports `learnings._apply_confidence_decay` (validates import path; side-effect only).
2. Runs `distill.run_distill_after_outcome(n=30)` -- the distillation tick.

### 8.4 Retention Policies

`apply_retention_policies(cfg)` (called daily by `_bg_cleanup`):

**Age-Based Policies** (configurable via `retention_<table>_days`):

| Table | Default Retention | Category |
|-------|-------------------|----------|
| `tool_outcomes` | 90 days | high-churn |
| `conversation_messages` | 90 days | high-churn |
| `outcome_evaluations` | 180 days | high-churn |
| `tool_calls` | 90 days | high-churn |
| `telemetry_events` | 90 days | high-churn |
| `model_outcomes` | 180 days | high-churn |
| `route_telemetry` | 90 days | high-churn |
| `conversation_summaries` | 365 days | low-churn |
| `relationship_memory` | 365 days | low-churn |
| `timeline_events` | 365 days | low-churn |
| `episode_events` | 365 days | low-churn |
| `goal_progress` | 365 days | low-churn |
| `aspect_memories` | 365 days | low-churn |
| `session_prompts` | 180 days | low-churn |
| `audit` (by `timestamp` col) | 365 days | special |
| `study_plans` (non-active) | 90 days | special |

**Hard Caps** (keep newest N rows):

| Table | Default Max Rows |
|-------|------------------|
| `tool_outcomes` | 50,000 |
| `conversation_messages` | 200,000 |
| `outcome_evaluations` | 5,000 |

**Additional Cleanup** (in `_bg_cleanup`):

- Audit log file rotation: keeps tail of `audit_log_max_bytes` (default 2 MB).
- Research output: deletes `.research_output/*.md` older than `retention_research_output_days` (default 90), preserving `last_research.md`.

### 8.5 Low-Confidence Pruning

`prune_low_confidence_learnings(threshold=0.08, batch=25)`:
1. **Archives first**: inserts into `learnings_archive` with `archive_reason="confidence_decay"`.
2. **Deletes from active table**: removes learnings with `confidence < threshold`.
3. **Cleans vectors**: deletes corresponding ChromaDB embeddings via `vector_store.delete_vectors_by_ids`.
4. Batch-limited to avoid long transactions.

### 8.6 Learning Reinforcement

`reinforce_learning(learning_id, success=True)`:
- When a learning contributed to a successful outcome, bumps its confidence by +0.04 (capped at 1.0).
- Only acts on success; no-op for failures.

---

## 9. Supporting Subsystems

### 9.1 Initiative Engine

`agent/services/initiative_engine.py` -- rule-based (no LLM) suggestion
generator:

- `collect_initiative_hints(state, cfg)`: Analyzes the last agent state for
  failed tools, outcome weaknesses, skill pack suggestions.  Returns up to 4
  hint strings.  Gated by `initiative_engine_enabled` (default: false).
- `wakeup_engine_hints(active_plans, cfg)`: Read-only wakeup suggestions about
  study plan count.  Gated by `initiative_engine_enabled`.
- `generate_project_proposals(workspace_root, cfg)`: LLM-based project idea
  generation from project memory.  Double-gated: `initiative_project_proposals_enabled`
  AND trust tier >= 2.

### 9.2 Initiative Inline

`agent/services/initiative_inline.py` -- appends a one-line suggestion to
assistant replies:

- Gated by `inline_initiative_enabled` OR `initiative_engine_enabled` (both
  default false).
- Triggers on fabrication keywords (DXF, toolpath, G-code), repeated tool use,
  multi-step workflows, weak outcomes.
- Falls back to generic "verify with read_file" suggestions.
- Optionally enriches with relationship codex context.
- Records suggestions to `initiative_ledger` when `initiative_ledger_enabled`.

### 9.3 Autonomy Optimizer

`agent/services/autonomy_optimizer.py` -- bounded recovery hints for governed
plan steps:

- `propose_step_recovery(failed_tool, validation_reason, step_tools, cfg)`:
  suggests an alternate tool from the step's allowlist (never widens
  permissions).  Gated by `autonomy_optimizer_enabled` (default: false).
- Prefers read/verify tools after write/run failures.

### 9.4 Journal Engine

`agent/services/journal_engine.py` -- structured session journaling:

- `add_entry(entry_type, content, tags, ...)`: Thin wrapper around `db.add_journal_entry`.
- `auto_session_recap(conversation_id)`: Deterministic, no-LLM recap builder.
  Extracts last 6 user + 4 assistant message highlights.  Saves as
  `entry_type="recap"` journal entry.

### 9.5 Background Job Worker

`agent/background_job_worker.py` -- subprocess entrypoint for spawn/background
agent jobs:

- Receives job JSON on stdin (or via `LAYLA_JOB_FILE` env var).
- Applies OS resource limits (POSIX rlimits, Windows job memory limits, Linux
  cgroups).
- Supports single-shot and continuous modes (up to 500 iterations with delay).
- Supports file-plan execution via `engine_plans.run_plan_iteration`.
- Emits NDJSON progress events on stderr.
- Writes final JSON result to stdout.

### 9.6 Worker Pool

`agent/services/worker_pool.py` -- advisory concurrency limits:

- `max_parallel_workers(cfg)`: Returns 1--6 based on hardware class
  (`potato`=1, `mid`=2, `strong`=4, `workstation`=6).  Overridable via
  `max_workers` config.  Disabled via `worker_pool_enabled=false` (forces 1).
- `tool_batch_max_workers(cfg, batch_len)`: Caps ThreadPoolExecutor for
  concurrent read-only tool batches.

### 9.7 Background Subprocess Manager

`agent/services/background_subprocess.py` -- OS process lifecycle for worker
jobs:

- `spawn_background_worker(job)`: Starts `background_job_worker.py` as a
  subprocess.  Pipes job JSON on stdin.  Attaches Linux cgroups or Windows job
  objects for memory limits.  Supports optional `background_worker_wrapper_command`
  config (e.g., `nice`, `ionice`).
- `cancel_worker(proc)`: SIGTERM -> wait -> SIGKILL escalation with psutil
  tree kill.  Handles both POSIX and Windows.
- `wait_worker_result(proc)`: Drains stdout (JSON) and stderr (progress NDJSON)
  with cap enforcement (`max_stdout_bytes=8MB`, `max_stderr_bytes=2MB`).
  Kills process if stdout exceeds cap.
- `cleanup_worker_cgroup(proc)`: Removes leaf cgroup on Linux.

---

## 10. Known Issues

### 10.1 Dead Code / Never-Scheduled Jobs

| Item | Location | Issue |
|------|----------|-------|
| `_airllm_warmup_job` | `jobs.py:242` | Defined but never imported into `registry.py`. Never runs. |
| `_syncthing_rescan_job` | `jobs.py:273` | Defined but never imported into `registry.py`. Never runs. |
| `run_codex_relationship_discovery` | `background_intelligence.py:102` | Only called by `run_all_jobs()` which itself is never invoked. |
| `run_spaced_repetition_review` | `background_intelligence.py:173` | Same -- only in `run_all_jobs()`. |
| `run_kb_synthesis_check` | `background_intelligence.py:227` | Same -- only in `run_all_jobs()`. Log-only (never auto-builds KB articles). |
| `apply_decay_if_needed` | `capabilities.py:329` | Decay function exists but is never called by any scheduler job or periodic hook. Capability decay is defined but not enforced. |

### 10.2 Config Gates That Are Always Off

| Config Key | Default | Effect |
|------------|---------|--------|
| `initiative_project_proposals_enabled` | `false` | `_bg_initiative` short-circuits immediately. |
| `initiative_engine_enabled` | `false` | `collect_initiative_hints` and `wakeup_engine_hints` return empty. |
| `inline_initiative_enabled` | `false` | `maybe_append_inline_suggestion` is a no-op (unless `initiative_engine_enabled` is also true). |
| `autonomy_optimizer_enabled` | `false` | `propose_step_recovery` returns `{"action": "none"}`. |
| `scheduler_use_capabilities` | `false` | Study plan selection ignores urgency/diversification; falls back to oldest `last_studied`. |
| `enable_lens_refresh` | `false` | Lens refresh job never registered. |
| `airllm_enabled` | `false` | Even if registered, warmup would skip. |

### 10.3 Missing Instrumentation

- `_bg_reflect`, `_bg_codex`, `_bg_memory`, `_bg_initiative`, `_bg_cleanup`,
  `_bg_repo_reindex`, `_intelligence_job`, `_scheduled_study_job`,
  `_rl_preference_job` are **not** wrapped with `_instrumented()`.
  Only `mission_worker`, `nightly_backup`, and `reindex_failed` get Prometheus
  metrics.

### 10.4 Suppressed Errors

- `_rl_preference_job` has a bare `except Exception: pass` -- failures are
  completely silent, no logging at all.
- Most job functions catch all exceptions and log at `warning` or `debug` level
  but there is no alerting or retry mechanism.
- `_bg_cleanup` has 4 levels of nested try/except suppression; any inner failure
  is silently swallowed.

### 10.5 Anonymous Job IDs

- `_scheduled_study_job` is registered without an explicit `id=`, making it
  harder to inspect or remove at runtime.
- `rebuild_lens_knowledge` (lens refresh) is registered without an `id=`.

### 10.6 Race Conditions and Thread Safety

- `activity._last_activity_ts` is a module-level float modified from API
  handler threads and read by scheduler threads.  Python's GIL makes this
  safe for single writes but the pattern is fragile and would break under
  a non-CPython runtime.
- `idle_detector._detector` singleton is initialized lazily without locking.
  Two threads calling `get_idle_detector()` simultaneously could create two
  instances (the first would be discarded).
- `_scheduler` global in `registry.py` is set once during startup, but
  `get_scheduler()` reads it without synchronization -- acceptable in
  practice since it is set before threads start.

### 10.7 Scheduler Not Stopped on Shutdown

There is no `atexit` handler or `lifespan` shutdown hook visible in the
scheduler module to call `scheduler.shutdown()`.  The caller (presumably
`main.py` lifespan) is responsible but this is not enforced.

### 10.8 Experience Replay Is Read-Only

`run_experience_replay()` computes tool patterns and reflections but does not
persist any heuristic updates.  The comment says "Heuristics could be stored
in style_profile or a dedicated table" -- this is not implemented.  The actual
feedback loop is in `rl_feedback.py`, not in `experience_replay.py`.

### 10.9 Consolidation Decay Import Is Side-Effect Only

`consolidate_periodic()` imports `_apply_confidence_decay` but never calls it.
The code reads:
```python
_ = _apply_confidence_decay  # module side effects: ensure import path valid
```
This suggests the decay was intended to run on import as a module side effect,
which is an unusual and fragile pattern. If the side effect was removed from
the `learnings` module, decay would silently stop.

---

## 11. Stability Assessment

| Component | File(s) | Rating | Notes |
|-----------|---------|--------|-------|
| **APScheduler setup** | `registry.py` | **STABLE** | Clean, well-clamped intervals, proper error boundaries. |
| **Job functions** | `jobs.py` | **STABLE** | Lazy imports, individual try/except. Main risk: silent failures. |
| **Idle detection** | `idle_detector.py` | **STABLE** | Well-structured but underused -- no scheduled job currently gates on it. |
| **Activity tracking** | `activity.py` | **STABLE** | Simple, low-risk module. Game detection is best-effort. |
| **Background intelligence** | `background_intelligence.py` | **FRAGILE** | 3 of 5 functions are orphaned. `run_all_jobs()` is dead code. Only `reflection_scan` and `codex_entity_nudge` are live. |
| **Knowledge distiller** | `knowledge_distiller.py` | **STABLE** | Clean LLM-with-fallback pattern. |
| **Experience replay** | `experience_replay.py` | **INCOMPLETE** | Read-only analysis. Does not actually update any heuristics. |
| **RL feedback** | `rl_feedback.py` | **STABLE** | Complete feedback loop: compute -> classify -> persist -> inject into prompt. |
| **Curiosity engine** | `curiosity_engine.py` | **STABLE** | Heuristic gap detection. No LLM dependency. |
| **Capability tracking** | `capabilities.py` | **STABLE** | Comprehensive growth model with decay, cross-domain, anti-specialization. |
| **Capability decay** | `capabilities.py:apply_decay_if_needed` | **DEAD** | Exists but never called. Capabilities can grow but never shrink. |
| **Self-improvement** | `self_improvement.py` | **STABLE** | Deterministic, narrow allowlist, operator-gated. |
| **Initiative engine** | `initiative_engine.py` | **INCOMPLETE** | Config-gated off by default. Project proposals require LLM + trust tier 2. |
| **Initiative inline** | `initiative_inline.py` | **FRAGILE** | Complex conditional logic with 6+ fallback tiers. Config-gated off by default. |
| **Autonomy optimizer** | `autonomy_optimizer.py` | **STABLE** | Simple, well-bounded. Config-gated off by default. |
| **Memory consolidation** | `memory_consolidation.py` | **STABLE** | Archive-before-delete pattern. Comprehensive retention policies. |
| **Journal engine** | `journal_engine.py` | **STABLE** | Thin wrappers, deterministic recap. |
| **Background job worker** | `background_job_worker.py` | **STABLE** | Robust subprocess with resource limits, progress streaming, continuous mode. |
| **Worker pool** | `worker_pool.py` | **STABLE** | Advisory limits only; simple and correct. |
| **Background subprocess** | `background_subprocess.py` | **STABLE** | Full process lifecycle with cross-platform support (POSIX/Windows), cgroup/job object integration. |

### Summary Counts

- **STABLE**: 14
- **FRAGILE**: 2 (background_intelligence, initiative_inline)
- **DEAD**: 1 (capability decay)
- **INCOMPLETE**: 2 (experience_replay, initiative_engine)

---

## 12. Data Flow Diagram

```
                    APScheduler (BackgroundScheduler, UTC)
                    ========================================
                    |                                      |
           Always-on jobs                        Gated by scheduler_study_enabled
           ---------------                      --------------------------------
           |                                     |            |              |
    mission_worker (2m)               study_job (30m)   intelligence (60m)  rl_pref (30m)
    bg_reflect (5m)                       |               |    |    |          |
    bg_codex (10m)                  capabilities.py   distill  replay  curiosity  rl_feedback.py
    bg_memory (30m)                   record_practice                            compute_prefs
    bg_initiative (30m)               get_next_plan                              upsert_rl_pref
    bg_cleanup (24h)                      |
    nightly_backup (24h)            study_service
    repo_reindex (30m)              run_autonomous_study
    reindex_failed (30m)

    Memory Write Paths:
    -------------------
    bg_cleanup ---------> prune_low_confidence (archive + delete)
                   |----> apply_retention_policies (age + cap deletes)
                   |----> audit log rotation (file truncation)
                   |----> research output cleanup (file deletion)

    bg_memory ----------> distill.run_distill_after_outcome (learning merge)

    bg_codex -----------> codex_db.upsert_entity (low-confidence entities)

    bg_initiative ------> llm_gateway.run_completion -> project proposals (if enabled)

    rl_pref ------------> rl_preferences table (tool scores + hints)

    study_job ----------> capability_events (practice/cross_signal)
                   |----> capabilities (level/confidence/trend update)
                   |----> scheduler_history (diversification tracking)

    intelligence -------> learnings (strategy insights from distiller)
                   |----> learnings (curiosity suggestions)
```
