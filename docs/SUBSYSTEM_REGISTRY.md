# Subsystem registry

Quick map of major agent subsystems, primary config flags, and interactions. Use this to avoid orphan flags and undocumented coupling.

| Subsystem | Module(s) | Key flags | Feeds policy caps? | Notes |
|-----------|-----------|-----------|-------------------|-------|
| Decision policy | `services/decision_policy.py` | `decision_policy_enabled` | — | Merges caps; clamps tool allowlist |
| Planner | `services/planner.py` | `planning_enabled`, `plan_system_first_enabled`, `plan_llm_gap_fill_only` | Indirect (plans) | Templates before LLM when enabled |
| Cognitive workspace | `services/cognitive_workspace.py` | `enable_cognitive_workspace` | Yes | Strategy hint → verify / forbid mutating |
| Outcome evaluation | `services/outcome_evaluation.py` | `planning_outcome_bias_enabled` | Yes | Last run score → verify / cap tools |
| Initiative (inline) | `services/initiative_inline.py` | `inline_initiative_enabled` | No (suggestions) | Ledger: `initiative_ledger_enabled` |
| Toolchain awareness | `services/toolchain_awareness.py` | — | Optional hints | Weighted DAG for planner text + policy hint |
| Memory merge | `services/context_merge_layers.py` | — | No | Memory block order |
| Fabrication IR | `layla/geometry/machining_ir.py` | `geometry_*` | No | `machine_readiness` on tool outputs |
| Blackboard | `shared_state.py` | — | No | Spawned agents post artifacts |
| Lite mode | `agent_loop.py` | `chat_lite_mode` | No | Disables macro-plan + cognitive workspace |
| Task budget | `services/task_budget.py`, `agent_loop.py` | `task_budget_enabled`, `force_full_pipeline`, `run_budget_summary_log_enabled`, `api_confidence_enabled` | Indirect (caps before PolicyCaps) | Composes with reasoning classifier; optional `langfuse_*` + `services/langfuse_export.py` |

## Kill-switch bundles (conceptual)

- **Expert**: default Layla behavior.
- **Lite**: set `chat_lite_mode: true` for fewer subsystems on the hot path.

## Policy invariants

- Nothing in learnings or memory retrieval may disable `require_approval` or sandbox checks. Ethics: [ETHICAL_AI_PRINCIPLES.md](ETHICAL_AI_PRINCIPLES.md).
