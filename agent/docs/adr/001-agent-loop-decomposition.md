# ADR-001: Agent Loop Decomposition

**Status:** Accepted  
**Date:** 2026-05-25  
**Context:** `agent_loop.py` was 4093 lines with a single 1404-line function (`_autonomous_run_impl_core`).

## Decision

Extract agent_loop.py into thin delegation wrappers + 11 service modules under `services/agent/`:

| Module | Responsibility | Lines |
|--------|---------------|-------|
| `llm_decision.py` | LLM decision routing, tool selection | ~520 |
| `stream_handler.py` | Streaming reason responses | ~290 |
| `tool_guards.py` | Pre-execution safety checks | ~145 |
| `run_finalizer.py` | Post-run state cleanup, telemetry | ~170 |
| `response_builder.py` | Response formatting | ~180 |
| `verification_engine.py` | Tool output verification | ~265 |
| `ux_emitter.py` | UX state queue management | ~140 |
| `tool_helpers.py` | Tool argument injection | ~130 |
| `run_setup.py` | Pre-loop init, planning, config | ~860 |
| `decision_loop.py` | Main while loop, tool dispatch | ~550 |
| `reasoning_handler.py` | Reason intent handling, LLM calls | ~370 |

## Consequences

- `agent_loop.py` reduced from 4093 to 1574 lines (62% reduction).
- Each module is independently testable.
- Backward compat maintained: original function signatures preserved as thin wrappers.
- No globals access from extracted modules; dependencies passed as parameters.
