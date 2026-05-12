# Memory Router Migration Tracker

Phase B Fix 3. Source of truth: `agent/docs/audit/subsystem_audit.md` §1.

The audit claimed ~33 files bypass `services/memory_router.py`. After narrowing
to the actual write-primitive imports (`save_learning`, `save_aspect_memory`)
the real list of production bypassers was 6 files. All 6 are now migrated.

## Files migrated this session

| File | Line | Was | Now |
|---|---|---|---|
| `services/memory_commands.py` | 81 | `from layla.memory.db import save_learning` | `from services.memory_router import save_learning` |
| `layla/tools/impl/memory.py` | 41, 111 | `from layla.memory.db import save_learning` | `from services.memory_router import save_learning` |
| `routers/learn.py` | 85 | `from layla.memory.db import save_learning` | `from services.memory_router import save_learning` |
| `services/study_service.py` | 12 | `from layla.memory.db import save_learning, update_study_progress` | router + db split |
| `main.py` | 549 | `from layla.memory.db import save_learning` (intelligence_job) | `from services.memory_router import save_learning` |
| `routers/memory.py` | 28 | `from layla.memory.db import get_recent_learnings, save_learning` | router + db split |

Lint check (`scripts/check_memory_router_enforcement.py`) reports **0 offenders**
for the `save_learning` / `save_aspect_memory` primitive imports.

## Out of scope for this fix (still tracked)

The audit's "33 files" figure also bundled writers of other primitives
(`record_tool_call`, `record_tool_outcome`, direct `_conn().execute("INSERT...")`,
Chroma `add_vector` calls). Those are legitimate consumer-storage layer calls
that don't fit the `save_learning` shape and were never wrapped by the router.

Decisions:

1. **`record_tool_call` / `record_tool_outcome` (in `core/executor.py`)** — keep
   as direct writers. The executor *is* the storage owner for episodic
   tool-call rows; adding a router pass-through buys nothing and adds latency
   on the hottest path in the system. The audit's framing ("episodic writers
   bypass router") is technically true but the right fix is to acknowledge the
   executor as the episodic-write authority in docs, not to wrap it.

2. **`add_vector` / Chroma upserts** — the router already routes *reads* through
   `_query_chromadb`. Direct vector writes happen in `layla/memory/vector_store.py`
   plus a handful of callers (`routers/learn.py:82`, `layla/tools/impl/memory.py:117`).
   Adding `memory_router.upsert_vector` is a one-hour change but not load-bearing
   for the audit's claim. Deferred to a future session.

3. **`_conn().execute("INSERT INTO ...")`** — grep shows these only inside
   `layla/memory/db.py`, `layla/memory/learnings.py`, `layla/memory/user_profile.py`,
   and `services/memory_router.py` itself. No production bypassers.

## Lint enforcement plan

- **Today:** `check_memory_router_enforcement.py` runs at WARN severity inside
  `run_all_checks.py`. 0 offenders for `save_learning` family.
- **Next:** Extend the lint to flag direct Chroma `add_vector` calls outside
  the storage layer, and add `memory_router.upsert_vector` pass-through.
- **Eventually:** Promote the check to FAIL once vector writes are also routed
  and the executor's `record_tool_*` exception is formally documented.

## Next session order

1. Add `services.memory_router.upsert_vector(...)` pass-through.
2. Migrate the ~3 `add_vector(...)` callers in routers/tools.
3. Extend lint to cover vector writes.
4. Document the executor's episodic-write exemption in `ARCHITECTURE.md`.
5. Ratchet enforcement check to FAIL severity.

## Test results

- `pytest tests/test_goal_preservation.py -v` → 4 passed.
- Full suite results — see commit body for the migration commit.
