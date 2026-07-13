# Audit Round 6 — data_state

- **Dimension:** data_state (weight 8, cadence 1)
- **Mode:** round
- **Reality anchor:** healthy = true, quality = degraded
- **Pushed:** yes
- **Quiescent now:** no · All quiescent: no
- **New failures introduced:** none

## Counts

| Metric | Count |
|---|---|
| Found | 15 |
| Auto-fixed (by the loop) | 4 |
| Reverted | 0 |
| Report-only (need a human) | 11 |

## Report-only findings

These survived the loop and require a human decision/fix.

---

### #1 — MEDIUM — knowledge_graph.graphml lost-update: unsynchronized read-modify-write clobbers concurrent writers
- **File:** `agent/services/memory/graph_learning.py:52`
- **Root cause:** `memory_graph`'s locked mutators (`add_node`/`add_edge`/`_save_graph`) serialize the whole RMW under `_graph_lock` (see comment at `memory_graph.py:16-19`), but the PUBLIC api splits it: `load_graph()` (`memory_graph.py:120`) reads the entire graph with NO lock held, and `save_graph()` (`memory_graph.py:138-147`) takes the lock only to rebuild-and-FULL-REPLACE from the caller's dict (no merge). `graph_learning.expand_graph_from_learning()` runs in a per-learning daemon thread (`learnings.py:246-257`, `name='graph-expand'`), and `add_node` is also called concurrently from `routers/learn.py:97`. Two overlapping writers each snapshot before either saves; the later `os.replace` wins and the earlier writer's nodes/edges are permanently lost. Per-write atomicity (temp+fsync+os.replace) is correct; the compound op is not atomic.
- **Fix sketch:** Make the RMW atomic — either (a) expose a locked mutate-in-place helper in `memory_graph` that holds `_graph_lock` across `_get_graph()`→callback→`_save_graph()`, used by graph_learning/add_node; or (b) have `save_graph()` merge into the on-disk graph under the lock instead of full-replacing a pre-lock snapshot.
- **Failing input:** Two learnings saved back-to-back, each spawning a graph-expand daemon. Thread A `load_graph()`→{e0}, computes e1. Thread B `load_graph()`→{e0}, computes e2. A `save_graph({e0,e1})` full-replaces; B `save_graph({e0,e2})` full-replaces. Disk = {e0,e2}; e1 lost silently. Same loss if a `/learn` add_node interleaves with a graph-expand thread whose snapshot predates it.

---

### #4 — MEDIUM — Mission crash-recovery re-executes side-effecting steps: "step-idempotent" premise is false
- **File:** `agent/services/planning/mission_manager.py:168`
- **Root cause:** `execute_next_step()` advances `current_step` only AFTER `autonomous_run()` returns (`mission_manager.py:135-147` run the step's side effects — allow_write writes, allow_run shell/build — then `:163-168` persist `current_step=next_step`). A mid-step crash never advances `current_step`. On restart `reap_orphaned_tasks()` marks the in-flight mission `paused` (`missions_db.py:289`) explicitly on the premise that "missions are step-idempotent (resume re-executes from current_step)" (`missions_db.py:265,280`). That premise is unfounded for allow_write/allow_run steps. On resume the SAME un-advanced step re-runs and repeats its side effects. No per-step in_progress/completed marker, no pre-execution advance.
- **Fix sketch:** Give steps an at-most-once recovery contract — persist per-step state ('started' before autonomous_run, 'completed' after) and on resume skip an already-'started' step (treat as needs-review, not blind re-run); or reap write/run-enabled missions to a non-auto-resumable 'interrupted' state (like background_tasks). At minimum stop asserting step-idempotency in the reaper docstring for allow_write/allow_run missions.
- **Failing input:** Mission with allow_write/allow_run 'running' at current_step=2. `execute_next_step()` calls autonomous_run for step 2 (writes files / runs commands); server killed before `update_mission_progress` advances to 3. Startup `reap_orphaned_tasks()` sets 'paused'. User `POST /mission/{id}/resume` → 'running' → `_mission_worker_job` (`jobs.py:119`) → `execute_next_step` re-reads un-advanced current_step=2 → re-executes step 2's writes/commands a second time.

---

### #5 — LOW — TaskQueue.reset_stuck(timeout_seconds) silently ignores its argument
- **File:** `agent/services/cluster/work_unit.py:361`
- **Root cause:** `reset_stuck(timeout_seconds=600)` builds `WHERE (julianday(?) - julianday(started_at)) * 86400 > timeout_s`, where `timeout_s` is the per-row `task_queue` column (default 300, `work_unit.py:151`), not the bound parameter. The only `?` binds 'now'; `timeout_seconds` is never referenced. Every caller's intended global override is a dead no-op — threshold is always the per-row column value.
- **Fix sketch:** Bind the parameter: `> ?` with params `(now, timeout_seconds)`; or, if per-row timeouts are intentional, drop the misleading `timeout_seconds` parameter.
- **Failing input:** Crashed node leaves a row status='running' with per-row timeout_s=3600 and stale started_at. Caller invokes `reset_stuck(300)` expecting reset after 300s; argument ignored, row not reset until now-started_at exceeds its own 3600s → lingers ~1 hour instead of 5 min. (Edge: NULL timeout_s → never reset, since numeric > NULL is false; DEFAULT 300 makes this unlikely.)

---

### #6 — MEDIUM — decisions.db grows unbounded — separate DB file missed by the central retention sweep
- **File:** `agent/services/memory/decision_memory.py:60`
- **Root cause:** `record_decision()` INSERTs one row per deliberation into a SEPARATE SQLite file (`~/.layla/decisions.db`, path `decision_memory.py:29-30`) opened with its own `sqlite3.connect` (`:37`), not shared `_conn()`/layla.db. `apply_retention_policies()` (`memory_consolidation.py:77-245`) only DELETEs from layla.db tables via `_conn()`, and `_bg_cleanup`'s VACUUM (`jobs.py:220-232`) only touches layla.db. So `decision` has no age retention, row cap, or decay. `run_deliberation()` (`cognitive_workspace.py:117-123`) calls it on every deliberated/thinking turn; each row stores goal[:2000]+rationale[:2000]+context[:2000]+alternatives JSON (multi-KB). Grows without bound over months.
- **Fix sketch:** Add an age/row-cap purge in decision_memory (keep newest N, or delete created_at older than retention window) invoked from `_bg_cleanup`; OR fold the store into layla.db so `apply_retention_policies` covers it.

---

### #9 — LOW — answer_feedback.db is INSERT-only with no retention, cap, or decay
- **File:** `agent/services/infrastructure/answer_feedback.py:100`
- **Root cause:** Stores ratings/corrections in a separate SQLite file (`~/.layla/answer_feedback.db`, path `:30-31`, own `sqlite3.connect` `:38`). The write path (`INSERT INTO answer_feedback`, `:100`) has no matching DELETE/cap/decay anywhere, and lives outside layla.db so `apply_retention_policies` / `_bg_cleanup` VACUUM never touch it. User-driven churn (thumbs-down + corrections) is lower, but still no upper bound over the app's lifetime.
- **Fix sketch:** Add an age/row-cap prune (keep newest N, or delete older than a window) called from `_bg_cleanup`; or move the table into layla.db.
- **Failing input:** Repeatedly `POST /feedback` (or `record_feedback`) with 👍/👎 over the lifetime → rows accumulate forever. `record_feedback` (`:98-105`) only INSERTs; `grep 'DELETE FROM answer_feedback'` = 0 hits; `apply_retention_policies` runs against layla.db via `_conn` and never enumerates answer_feedback.

---

### #10 — MEDIUM — Central test-isolation fixture only isolates layla.memory.db; three stores stay pointed at the operator's real DBs
- **File:** `agent/tests/conftest.py:118`
- **Root cause:** The autouse session fixture `_force_test_db_path` (`conftest.py:118-141`) sets `LAYLA_DATA_DIR` and patches only `layla.memory.db._DB_PATH` + resets that module's `_MIGRATED`. But three other stores capture their path at IMPORT time into a module global that never reads `LAYLA_DATA_DIR`, each gated behind a process-global 'done' flag: `skill_registry.py:19` `_DB_PATH = Path.home()/.layla/skill_registry.db` (cached `_conn`, `:21,27`); `tunnel_audit.py:27-28` (`_table_ready`, `:34,53`); `repo_indexer.py:31-34` `_DEFAULT_DB = _AGENT_DIR/.layla/repo_index.db` (`_MIGRATED`, `:33,57`). None patched by the central fixture, so isolation depends on every test manually patching BOTH path AND guard (see the dance in `test_full_pipeline.py:116-139` resetting `sr._conn`, and `test_tunnel_flow.py:70,73` resetting `ta._table_ready`). Any test exercising these without that dance reads/writes the operator's real `~/.layla/*.db` (or the source-tree repo_index.db).
- **Fix sketch:** Have these three stores resolve their path lazily from `LAYLA_DATA_DIR` per connection (as decision_memory/macros already do), and/or extend the session conftest fixture to patch+reset `repo_indexer._DB_PATH/_MIGRATED`, `skill_registry._DB_PATH/_conn`, `tunnel_audit._DB_PATH/_table_ready`.
- **Failing input:** Run `pytest agent/tests/test_skill_rollback.py` standalone. No skill_registry-isolation fixture, yet `TestCanRollback.test_returns_bool` calls `can_rollback("any-pack")` → `get_pack()` → `_get_conn()`, and `TestRollbackInstall` calls `rollback_install(...)` → `unregister()` → `_get_conn()`. With `_DB_PATH` at its import default, `_get_conn` opens/CREATE-TABLEs the operator's real DB and caches `_conn` process-wide.

---

### #11 — LOW — repo_indexer.migrate() short-circuits on a process-global _MIGRATED, leaving a removed/replaced default DB schemaless
- **File:** `agent/services/workspace/repo_indexer.py:57`
- **Root cause:** `migrate()` guards `if _MIGRATED and db_path is None: return` (`:57`) and sets `_MIGRATED=True` once per process (`:105`). The guard tracks a boolean, not the resolved DB file. Every read API (`get_symbols:373`, `get_file_symbols:406`, `get_callers_of:428`, `get_stats:443`) and `index_file:227` call `migrate(None)` first, but once True that's a no-op, while `_conn()` (`:42-44`) unconditionally `sqlite3.connect`s — silently CREATING a new empty file if the default was deleted/rotated at runtime. Empty DB has no tables → every query raises 'no such table', is swallowed (`get_symbols` except at `:394` returns []), inserts fail — permanently until process restart resets `_MIGRATED`.
- **Fix sketch:** Key the guard to the resolved path (a set of migrated paths), or drop the flag and rely on cheap `CREATE TABLE IF NOT EXISTS` each call (as `decision_memory.py:33-53` does), so a recreated DB is re-migrated.
- **Failing input:** Long-lived server on default DB (`db_path=None`; production path `main.py:339`, `jobs.py:285`, `rules_engine.py:149`, `world_state.py:43`). After first `migrate()` sets `_MIGRATED=True`, an external actor deletes/moves `agent/.layla/repo_index.db`. Next `get_symbols()`/`get_stats()`/`index_workspace_repo()` calls `migrate(None)` → short-circuits at `:57`, then `_conn()` recreates an empty tableless file. Reads raise 'no such table' (swallowed), inserts raise until restart.

---

### #12 — HIGH — Auto-compact daemon self-deadlocks on non-reentrant llm_generation_lock, wedging all local inference
- **File:** `agent/services/context/context_manager.py:174`
- **Root cause:** `_compress_to_summary` acquires `busy_lock` and holds it across `run_completion()` (`:183`). In `llm_serialize_per_workspace=true` mode, `busy_lock = llm_generation_lock` — a plain, NON-reentrant `threading.Lock` (`llm_gateway.py:89`). Inside that call, `run_completion` (`llm_gateway.py:830`) recomputes `infer_lock = llm_generation_lock` and passes it to `inference_router.run_completion_llama_cpp`, which does `with _llm_lock:` (`inference_router.py:294/327`) — the SAME lock, on the SAME thread. A non-reentrant Lock re-acquired by its holder blocks forever. The daemon thread wedges holding `llm_generation_lock`; since every local completion in per-workspace mode acquires it, ALL local generation freezes process-wide. The default (non-per-workspace) path uses the RLock `llm_serialize_lock`, which is reentrant, masking the bug.
- **Fix sketch:** Do not hold `busy_lock` across the nested `run_completion` — release the admission/busy lock before calling it (it re-serializes internally); or make `llm_generation_lock` an RLock; or pass a flag so the inner call skips lock acquisition when the caller already holds it.
- **Failing input:** Set `llm_serialize_per_workspace: true` (default false, `runtime_safety.py:362`) with local llama_cpp + completion cache off/miss. Push a conversation past 0.75*n_ctx so an assistant turn spawns the `auto-compact` daemon (`shared_state.py:153`) → maybe_auto_compact → summarize_history:102 → `_compress_to_summary`. Daemon grabs `llm_generation_lock` (non-blocking) at `context_manager.py:174`, then `run_completion(stream=False)` re-enters the SAME lock at `inference_router.py:327` → self-deadlock. Every later local completion then blocks → all local inference frozen.

---

### #13 — HIGH — Local LLM timeout detaches the worker but releases _llm_lock, allowing concurrent native access to the same Llama instance (heap corruption)
- **File:** `agent/services/llm/inference_router.py:349`
- **Root cause:** In the non-streaming llama_cpp path, `_call_create_completion` runs in a ThreadPoolExecutor worker inside `with _llm_lock:`. On `_cf.TimeoutError` the code does `ex.shutdown(wait=False, cancel_futures=True)` and returns from inside the `with` block (`:349-350`), releasing `_llm_lock`. But `cancel_futures` cannot cancel an already-started future, so the detached worker keeps running `llm.create_completion()` on the shared `Llama` instance with the lock now free. The next caller acquires `_llm_lock` and runs `llm._ctx.kv_cache_clear()`, `llm.reset()`, `llm.create_completion()` on the SAME instance concurrently. llama-cpp-python releases the GIL during C inference → a true data race on native KV-cache/context memory (corruption, crash, garbage). The timeout path defeats the single-in-flight invariant `_llm_lock` exists to enforce; the code comment even acknowledges the still-running worker holds a live reference.
- **Fix sketch:** On timeout treat the instance as poisoned — keep the lock held until the worker actually finishes, or fence off the instance (invalidate/replace under a guard the worker respects) so no other caller touches it, rather than releasing the shared lock while native work is in flight.
- **Failing input:** Local llama_cpp. Request A issues a non-streaming completion whose native call hangs past `max(10, llm_local_timeout_seconds)` (default 180s). At `inference_router.py:344` `fut.result` raises TimeoutError; `:349` shutdown does NOT cancel/join the started worker; `:350` returns out of `with _llm_lock:`, releasing it. Detached worker keeps running. Request B (retry from the returned "Local LLM timed out. Please retry." message, or a concurrent workspace/idle/background completion) acquires the freed lock → `_call_create_completion` → `kv_cache_clear()/reset()/create_completion()` (`:280-288`) on the SAME instance. GIL dropped during C inference → both threads mutate native memory → heap corruption/crash/garbage.

---

### #14 — MEDIUM — Auto-compact history swap uses a length-only staleness guard that fails at deque maxlen, dropping newest turns
- **File:** `agent/shared_state.py:145`
- **Root cause:** `_compact_bg` snapshots the conversation deque under `_conv_hist_lock`, runs the multi-second LLM summarizer with the lock RELEASED, then re-acquires and guards the swap with `if len(h1) != snap_len: return`. The guard only compares LENGTH. At the deque's `maxlen` (default 20 via `get_conv_history`), concurrent `append_conv_history` calls during summarization append new turns while auto-evicting the oldest — so `len(h1)` stays == `snap_len`. Guard passes, `h1.clear()` runs, deque repopulated from the STALE pre-summary snapshot (`compacted`), discarding turns that arrived during summarization. The inline comment claims audit #12 fixed this, but length-only cannot detect content changes when the deque is saturated.
- **Fix sketch:** Guard on identity/content, not length — capture a monotonic revision counter (or snapshot object identity) under the lock and abort the swap if it changed; or append-diff rather than clear()+repopulate.
- **Failing input:** Deque saturated at maxlen=20. Assistant turn N completes → `_compact_bg` snapshots [m1..m20] (snap_len=20) under lock, releases, runs maybe_auto_compact (seconds). Meanwhile user sends turn N+1: `append_conv_history` appends user+assistant; deque full → evicts m1,m2 → holds [m3..m22], len still 20. `_compact_bg` re-acquires, `20 != 20` is False → guard passes. `h1.clear()` repopulates from stale [m1..m20]. Result: m21/m22 (newest exchange) dropped, evicted m1/m2 resurrected. Next prompt via `get_conv_history` (`routers/agent.py:448`) is missing the most recent turn.

---

### #15 — LOW — Cancellation endpoints are dead-wired: shared _cancel_events registry never populated in production
- **File:** `agent/routers/system.py:873`
- **Root cause:** `POST /agent/cancel/{conversation_id}` (`system.py:866`) and `DELETE /agent` (`:896`) rely on `shared_state.set_cancel(cid)` and `get_most_recent_conv_id()`, which read `_cancel_events` and `_most_recent_conv_id` (`shared_state.py:460-500`). Those are only written by `new_cancel_event()`, called from NOWHERE in production (only tests). So `_cancel_events` is always empty: `set_cancel` always returns False (`{ok:false}`), `get_most_recent_conv_id()` always None (`DELETE /agent` → 'no active conversation'). The agent loop never consults these asyncio.Events either — it cancels via a separately-wired `client_abort_event` (threading.Event) driven by `_watch_client_disconnect`. The whole asyncio.Event cancel subsystem is orphaned; explicit user cancel-by-conversation-id is silently non-functional.
- **Fix sketch:** Either wire `new_cancel_event()` into the run entry points (and make them threading.Events, since `set_cancel` is called from sync handlers), routing cancel to the agent loop's abort check; or delete the dead endpoints/registry and document that cancellation is disconnect-driven only.
- **Failing input:** Client calls `POST /agent/cancel/{conversation_id}` (route `main.py:921`) to stop an in-flight run. `system.py:873` calls `shared_state.set_cancel(cid)`, reading the module-level `_cancel_events` (`shared_state.py:484`), written only by `new_cancel_event()` which no production code calls. Dict always empty → `set_cancel` False → endpoint always `{ok:false}`; run not cancelled. `DELETE /agent` (`:902`) likewise: `get_most_recent_conv_id()` always None → `{ok:false, "error":"no active conversation"}`.
