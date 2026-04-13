# LangGraph — evaluation notes (adapter pattern, not a migration)

## Fit with Layla today

The production executor is **`agent_loop.autonomous_run`**: a single-threaded loop (decision JSON → tool → reason → telemetry). **LangGraph** models the same shape as a **graph of nodes** (classify → plan → tool → verify → respond) with explicit edges and optional human-in-the-loop interrupts.

**Full replacement** of `autonomous_run` with LangGraph as the only backend would be a large rewrite and would need every node to remain **offline-capable** (local GGUF, no cloud by default), preserving the **approval gate** and **sandbox** invariants from `AGENTS.md`.

## Pros of a future thin adapter

- **Explicit state machine** for multi-step flows (research missions, engineering pipeline) with named checkpoints.
- **Resume / branch** semantics can be clearer than ad-hoc `state["status"]` strings (if mapped carefully).
- **Optional** tracing hooks align with observability goals (alongside `run_budget_summary`, not requiring cloud).

## Cons / costs

- **Dual maintenance** during transition: two execution paths or a compatibility shim.
- **Streaming**: Layla’s `stream_pending` + `stream_reason` path would need a graph node contract that matches SSE and client abort semantics.
- **Tool governance**: per-step allowlists, `plan_step_governance`, and PolicyCaps would need to live **inside** or **around** graph nodes, not as a side channel.

## Suggested mapping (conceptual)

| Current | LangGraph node (conceptual) |
|--------|-----------------------------|
| `classify_reasoning_need` + task budget | `profile` / `budget` node |
| `should_plan` + `create_plan` | `plan` node (conditional edge) |
| `_llm_decision` | `decide` node |
| Tool execution + approval | `tool` node(s) with interrupt on `approval_required` |
| `_completion` / `stream_reason` | `respond` node |
| `validate_step_outcome` | `verify` node on governed branches |

## Recommendation

Treat LangGraph as a **future optional adapter** behind something like `execution_backend` only if a concrete use case needs graph-native HITL or branching. Until then, extend the existing loop (task budget, plan governance, observability) — as implemented in `services/task_budget.py` and `agent_loop.py`.
