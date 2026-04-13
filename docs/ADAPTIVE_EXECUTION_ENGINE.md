# Adaptive execution engine (budget-aware runtime)

Layla composes **task profiling** and a **budget envelope** with the existing reasoning classifier, planner gates, and **PolicyCaps** (`services/decision_policy.py`). Nothing here replaces the whole loop; it tightens caps and retrieval in a single, explainable place.

## Flow

1. **Config merge** — `runtime_safety.load_config()` + `chat_lite_mode` overlay (disables macro-planning and cognitive workspace).
2. **Reasoning mode** — `classify_reasoning_need` → `performance_mode: low` deep→light cap → `stabilize_reasoning_mode`.
3. **Task budget** (when `task_budget_enabled`, default on) — `services/task_budget.profile_task()` + `allocate_budget()`:
   - Adjusts effective `reasoning_mode` for the run (e.g. research forces deep).
   - Sets `max_plan_depth` on the **effective config** for this run (caps macro-plan nesting vs `max_plan_depth`).
   - Caps `max_tool_calls` after the token-pressure cap (minimum of envelope and config).
   - Sets `state["budget_retrieval_depth"]` (`minimal` | `normal` | `deep`); `_build_system_head` skips expensive RAG when `minimal`.
   - Sets `state["macro_planning_allowed"]`; in-loop `should_plan` is skipped when false.
4. **Quick reply** — Unchanged unless `force_full_pipeline: true` (debug/CI): then the trivial-turn fast path is disabled.
5. **Decision loop** — PolicyCaps still clamp tools each tick; envelope sets the **base** caps before policy merges.

## Observability

- **`state["pipeline_variant"]`**: `quick_reply` | `full` | `stream_only` (streaming final without inline completion in-process).
- **`state["run_budget_summary"]`** (and top-level `/agent` JSON): wall time (ms), tool call count, estimated conversation + goal tokens, optional estimated system-head tokens, reasoning mode, pipeline variant, goal hash (from task profile).
- **`log_run_budget_summary`** (`services/observability.py`) — one structured log line per run when `run_budget_summary_log_enabled` is true.
- **`confidence`** on `/agent` responses: from `services/outcome_evaluation.api_confidence_heuristic` — **not calibrated**; do not treat as a probability.

## Plan step validation (optional)

Governed plan steps may include string fields:

- **`validation_hint`** — documentation for humans/LLM; not executed.
- **`success_criteria`** — cheap checks in `validate_step_outcome`: `nonempty` / `nonempty_reply`, `substring:foo`, or plain substring match against the final reply text.

## Related config keys

See `agent/runtime_config.example.json`: `task_budget_enabled`, `force_full_pipeline`, `run_budget_summary_log_enabled`, `api_confidence_enabled`, optional `langfuse_*` (requires `pip install langfuse`).

## Relation to PolicyCaps

The envelope sets **run-level** caps (tools, plan depth, retrieval). **PolicyCaps** apply **per decision tick** from outcome/cognitive signals. Both can reduce capability; neither bypasses approval or sandbox.
