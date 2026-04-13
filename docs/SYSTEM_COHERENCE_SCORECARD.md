# System coherence scorecard

Measurable targets for architecture clarity, subsystem coupling (policy enforcement), safety, product usability, and coherence. Update this file when a phase closes.

## Dimensions

| Dimension | Target 9.0 meaning | Exit tests |
|-----------|-------------------|------------|
| Architecture clarity | Every major subsystem listed in [SUBSYSTEM_REGISTRY.md](SUBSYSTEM_REGISTRY.md) with owner flag(s) | Registry row exists; grep shows config key documented |
| Real intelligence (coupling) | At least five subsystems contribute to `PolicyCaps` via [decision_policy.py](../agent/services/decision_policy.py); tool allowlist reflects caps | `pytest agent/tests/test_decision_policy.py` |
| Safety | Approval gate and sandbox unchanged; policy layer cannot disable approvals from learnings | Existing approval/sandbox tests pass; no code path sets `require_approval` false from DB |
| Product usability | `chat_lite_mode` shortens default path; optional decision trace for power users | Manual: lite run skips macro-plan; `/settings` exposes lite flag |
| System coherence | [MEMORY_PRECEDENCE.md](MEMORY_PRECEDENCE.md) order implemented for memory block assembly | `pytest agent/tests/test_context_merge_layers.py` |

## Program rule

No phase ships without updating the relevant row above and adding or extending a test that proves **enforcement** (not only new prompt text).

## Current baseline (editorial)

Scores are subjective until each exit test is green. Track dates in git history when updating this section.
