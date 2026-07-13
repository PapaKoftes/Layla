# Audit Round 4 — Dimension: meta

- **Dimension:** meta (test health, dead/orphan modules, docs-vs-reality drift, dependency pins)
- **Mode:** round
- **Reality anchor:** healthy — quality **good** (app drives real turns end-to-end; no regressions surfaced this round)
- **Pushed:** yes

## Counts

| Metric | Count |
|---|---|
| Found | 7 |
| Auto-fixed by loop | 2 |
| Reverted | 0 |
| Report-only (need a human) | 5 |
| New failures introduced | 0 |

- **Quiescent now:** no
- **All dimensions quiescent:** no

## Report-only findings

All five report-only findings this round are **LOW** severity. Common theme: dead/orphan surface — modules and editable config keys that are declared and exposed but never dispatched or read at runtime.

---

### #1 — LOW — test_conftest_isolation.py isolation guards are order-dependent vacuous pairs

- **File:** `agent/tests/test_conftest_isolation.py:52`
- **Root cause:** The safety-net tests that verify the autouse isolation fixture actually works are implemented as split populate→verify test PAIRS (`test_config_cache_reset_between_tests_first` / `test_config_cache_was_cleared_by_autouse_fixture` at :52-69; the learnings pair at :72-91). They only detect a broken `_reset_volatile_module_state` fixture when run in deterministic definition order with the populator immediately before the verifier. There is no fixture-based or same-test assertion tying them together.
- **Fix sketch:** Make each guard self-contained: within a single test, set the sentinel, then trigger a fixture cycle (or assert against a helper that runs the reset) and check it was cleared — so the invariant holds regardless of collection order and doesn't leave global deque state behind on failure.
- **Failing input:** `pytest agent/tests/test_conftest_isolation.py::test_config_cache_was_cleared_by_autouse_fixture` (run alone, or any `-k` / random-order selection where the verifier runs without its populator immediately preceding). With `runtime_safety._config_cache` defaulting to `None`, the assertion at line 66 short-circuits true even if `_reset_volatile_module_state` were disabled — so the guard cannot detect a broken autouse fixture. Same for the learnings pair when reordered.

---

### #2 — LOW — Pluggable vector backend never dispatched: vector_backend/qdrant_* config keys are dead and layla/memory/vector_qdrant.py is an orphan module

- **File:** `agent/layla/memory/vector_qdrant.py:1`
- **Root cause:** A complete ~155-line Qdrant memory backend (`get_client`/`ensure_collection`/`add_memories`/`search_memories`/`delete_memories`/`get_stats`) exists and is gated on `vector_backend: "qdrant"`, but NO production code ever imports `vector_qdrant` OR reads the `vector_backend` config key to dispatch. Every memory read/write path calls `layla.memory.vector_store` (chroma) directly (`services/retrieval/__init__.py`, `services/prompts/system_head_builder.py`, `layla/tools/impl/memory.py`, `services/memory/memory_commands.py`). The dispatch layer that would branch on `vector_backend` was never written, so the whole module plus the `vector_backend`, `qdrant_url`, `qdrant_api_key`, `qdrant_collection` config keys are dead surface.
- **Fix sketch:** Either wire a real dispatch (have `vector_store` or the retrieval layer read `cfg['vector_backend']` and delegate to `layla.memory.vector_qdrant` when `'qdrant'`), or delete `vector_qdrant.py` plus the `vector_backend`/`qdrant_*` keys from `runtime_safety.py:754-757` and `config_migrator.py`.
- **Failing input:** User sets `"vector_backend": "qdrant"` (and `qdrant_url`) in runtime config expecting memories to route to Qdrant; effect is a silent no-op — ChromaDB (`layla.memory.vector_store`) is always used.

---

### #3 — LOW — capabilities/registry.py advertises 5 alternative implementations whose modules do not exist (capabilities/impl/ package is missing)

- **File:** `agent/capabilities/registry.py:51`
- **Root cause:** `CAPABILITIES` lists non-default impls with `module_path='capabilities.impl.faiss_vector'` (line 44), `'capabilities.impl.qdrant_vector'` (line 51), `'capabilities.impl.openai_embed'` (line 67), `'capabilities.impl.cohere_rerank'` (line 83), and `'capabilities.impl.bs4_scraper'` (line 99). The entire `capabilities/impl/` package does not exist in the repo. `get_active_implementation()`/`_module_importable()` (lines 183-215) therefore always fail to import these and silently fall back to the default, so these five "implementations" — and the `capability_impls` config override + `config_keys=['openai_api_key']`/`['cohere_api_key']` they advertise — are permanently unreachable placeholders. (Note the real Qdrant code that WAS written lives at `layla/memory/vector_qdrant.py`, a different path than the registry's `capabilities.impl.qdrant_vector` — the two are disconnected.)
- **Fix sketch:** Remove the five phantom entries (or create the `capabilities/impl/` adapter modules). For qdrant, point the registry at the existing `layla.memory.vector_qdrant` instead of the nonexistent `capabilities.impl.qdrant_vector`.
- **Failing input:** Config `{"capability_impls": {"vector_search": "faiss"}}` (or qdrant/openai/cohere/beautifulsoup) never takes effect: the ChromaDB/default stack is used regardless. Even reaching the module-import fallback described in the finding requires a call the production code never makes.

---

### #4 — LOW — config_migrator.py is an orphan: migrate_config is never called at startup or in load_config

- **File:** `agent/services/infrastructure/config_migrator.py:90`
- **Root cause:** The module exposes `migrate_config()`/`get_migration_status()` intended to persist newly-added default keys into an existing user's `runtime_config.json` (its own module docstring at lines 10-11 shows `from services.infrastructure.config_migrator import migrate_config; cfg, changes = migrate_config(cfg)` as the intended call site). No production code performs that call — `runtime_safety.load_config()` (`runtime_safety.py:291`) instead merges a large inline `defaults` dict at read time and never invokes the migrator. The module is referenced only by its own docstring and `tests/test_config_migrator.py`, making it dead code (the on-disk config is never actually migrated/upgraded).
- **Fix sketch:** Either call `migrate_config()` once from `load_config()`/first-run startup and write back the upgraded config, or delete `config_migrator.py` + its test since `load_config`'s inline default-merge already covers runtime resolution.

---

### #5 — LOW — Dead editable config key engineering_pipeline_max_clarify_rounds — exposed in Settings UI but never read

- **File:** `agent/config_schema.py:213`
- **Root cause:** The key is declared in `EDITABLE_SCHEMA` (category 'safety', type number, min 1 / max 10, default 3) and defaulted in `runtime_safety.py:694` and `runtime_config(.example).json`, so it renders as a live numeric control in the Settings UI — but no code anywhere reads it (repo-wide grep for `max_clarify_rounds`/`clarify_rounds` finds only the schema entry and the runtime_safety default). The hint honestly says 'Reserved', yet it's still a user-facing knob that silently does nothing. Contrast the sibling `engineering_pipeline_validator_max_retries` (`config_schema.py:222`), which IS read at `engineering_pipeline.py:536`.
- **Fix sketch:** Either wire the value into the engineering pipeline's clarification loop, or remove it from `EDITABLE_SCHEMA` (keep it only as an internal default if truly reserved) so the UI doesn't expose a no-op control.

---

## Summary

The reality anchor is green and no failures were introduced. This round surfaced a consistent dead-surface pattern: two orphan modules (`vector_qdrant.py`, `config_migrator.py`), a phantom `capabilities/impl/` package advertised by the registry, and a no-op Settings UI knob (`engineering_pipeline_max_clarify_rounds`), plus an order-dependent test-isolation guard. All five are LOW severity and need a human decision (wire vs. delete). The dimension is **not quiescent**; 5 open findings carried to the ledger.
