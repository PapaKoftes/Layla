# ADR-002: SessionContext Replaces shared_state Globals

**Status:** Accepted  
**Date:** 2026-05-25  
**Context:** `shared_state.py` stored per-conversation mutable state in module-level dicts with manual locks. No scoping, no cleanup, no TTL.

## Decision

Introduce `services/session_context.py` with a `SessionContext` class that:

1. Scopes all mutable state to a conversation ID
2. Uses a single `threading.RLock` per session (vs 8 separate locks in shared_state)
3. Provides typed accessors: steer hints (FIFO deque), outcome evaluation, coordinator trace, execution snapshot, decision trace, blackboard (with TTL), workspace leases (with TTL), cancellation events
4. Registry: `get_or_create_session()`, `get_session()`, `remove_session()`, `list_sessions()`

Migration is incremental:
- Phase A (done): shared_state functions now delegate to SessionContext internally (adapter pattern)
- Phase B (done): 7 service files migrated to import SessionContext directly (20 -> 13 importers)
- Phase C (future): migrate routers, deprecate shared_state entirely

## Consequences

- Per-conversation state is properly scoped and garbage-collectable.
- DB persistence added to `set_outcome_evaluation` (writes to SQLite + in-memory).
- Thread safety improved: one RLock per session vs 8 global locks.
- Shared_state continues to work for unmigrated callers (adapter pattern).
