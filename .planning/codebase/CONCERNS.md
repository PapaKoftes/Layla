---
last_mapped_commit: dc0b9c0ad8bdb1cba9afea771ad54a55473ec14d
---
# Codebase Concerns

**Analysis Date:** 2026-06-29

> Observational cartography. Each item is a structural risk a fresh reader would flag from the code itself, with file:line evidence. No remediation is asserted as done unless the code shows it.

## Tech Debt

**Complexity hotspot — `agent_loop.py` (4119 lines):**
- Issue: The single largest module in the repo holds 58 top-level defs/classes (`agent/agent_loop.py:22` through `:4119`), spanning UX emission (`_emit_tool_start`, `_emit_context_window_ux`), tool verification (`_apply_deterministic_tool_verification:233`, `_verify_tool_progress:1414`), streaming (`stream_reason:770`, `_stream_reason_body:821`), grant/approval logic (`_has_any_grant:1016`, `_write_pending:1053`), reflection (`_reflect_on_response:1115`), and tool selection (`_get_tools_for_goal:1266`). The core agent control flow, the UX layer, the safety/approval layer, and tool routing are all interleaved in one file.
- Files: `agent/agent_loop.py`
- Impact: Any change to streaming, approval, or tool dispatch touches a 4000-line file with no clear seams; high merge-conflict and regression surface. The agent loop is the system's critical path and the hardest file to reason about.
- Fix approach: Extract cohesive concerns (UX emission, approval/grant, tool verification, streaming body) into the already-existing sibling modules (`agent/services/agent_loop_formatting.py`, `agent/services/agent_safety.py`, `agent/services/agent_hooks.py` exist but the loop still inlines much of this).

**Other complexity hotspots (lines):**
- `agent/layla/memory/vector_store.py` (1410) — Chroma access layer; repeatedly re-instantiates `chromadb.PersistentClient` (`:167`, `:212`, `:370`) and lazy-imports the SQLite barrel back into itself (`:222`, `:467`, `:579`) — see Coupling.
- `agent/layla/memory/migrations.py` (1362) — schema migration engine; large hand-rolled migration ladder for the SQLite system-of-record.
- `cursor-layla-mcp/server.py` (1296) — separate MCP server surface, partly duplicating agent capabilities.
- `agent/layla/tools/impl/file_ops.py` (1158), `agent/services/tool_dispatch.py` (1122), `agent/services/system_head_builder.py` (1086), `agent/layla/tools/impl/general.py` (1082), `agent/routers/agent.py` (1076) — each is a single-file god-module for its domain.

**Lazy back-reference imports as a coupling smell:**
- Issue: Multiple modules import their dependency *inside* a function to break an import cycle rather than fix the layering. `agent/services/inference_router.py:400` does `from services.llm_gateway import llm_serialize_lock` inside the call; `agent/layla/memory/vector_store.py:222/467/579` lazy-imports `layla.memory.db` (the SQLite layer) from inside the Chroma layer; `agent/services/agent_task_runner.py:75`, `agent/services/engineering_pipeline.py:325`, `agent/services/initiative_inline.py:89` each lazy-import `layla.tools.registry.inside_sandbox`.
- Impact: The dependency graph is real but hidden; static tools won't see these edges, and the cycles indicate the memory/inference/tools layers are not cleanly separated.

## Configuration Sprawl

**Two parallel config systems / two config files:**
- Issue: The real system-of-record is `runtime_config.json`, loaded by `runtime_safety.load_config()` (`agent/runtime_safety.py:54`, `:186`); `agent/main.py` calls `runtime_safety.load_config()` everywhere (`:145`, `:319`, `:345`, `:404`, `:750`...). Separately, `agent/services/config_cache.py:6` defines `_CFG_PATH = .../config.json` (a *different* file) with its own `get_config()`/`cfg_get` (`:11`, `:28`), and 25 modules import `config_cache`.
- Files: `agent/runtime_safety.py:54`, `agent/services/config_cache.py:6`
- Impact: Two loaders read two different JSON files (`runtime_config.json` vs `config.json`) with independent caches and invalidation paths (`runtime_safety.py:109` clears one; `config_cache.py:7` guards the other). A reader cannot tell from a `cfg.get("x")` call site which file/cache is authoritative, and the two can drift.
- Fix approach: Collapse to a single loader; if `config.json` is legacy, document and remove.

**Documented-vs-actual key surface:**
- `agent/config_schema.py` (348 lines) documents ~the `runtime_config.json` schema and points users at `docs/CONFIG_REFERENCE.md` (`:4`). There are ~60 distinct `cfg.get("...")` keys in use across `agent/`; verifying every runtime key is represented in the schema is a manual audit (schema is a hand-maintained list, not derived from the code).

## Single Points of Failure / Scale

**One process, one model, one global generation lock:**
- Process: launched as a single uvicorn worker — `launcher.py:115` runs `uvicorn main:app --host 127.0.0.1` with no `--workers`; `layla.py:52` documents the same single-process invocation. There is no horizontal worker model.
- Model: local llama_cpp uses a single resident model — `agent/services/inference_router.py:407` comment "local llama_cpp uses single model"; the resident-model cache is capped at 2 (`agent/services/llm_gateway.py:22` `_DEFAULT_MAX_RESIDENT_MODELS = 2`, eviction at `:554`).
- Global lock: `agent/services/llm_gateway.py:76` `llm_generation_lock = threading.Lock()` serializes all local `create_completion` calls "so two workspaces never call create_completion concurrently" (`:74-76`); a legacy `_llm_lock = threading.RLock()` (`:69`) is aliased as `llm_serialize_lock` (`:72`) and imported by the agent loop. Per-workspace RLocks (`:78`, `get_agent_serialize_lock:82`) sit on top but all funnel through the one generation lock.
- Impact: Throughput is bounded to one in-flight local generation. A hung generation while holding `llm_generation_lock` stalls every workspace. Concurrency is a layered-lock scheme around a hard single-model serialization point — correct for memory safety, but the system's central scalability ceiling.

**Redundant / overlapping inference infra:**
- `agent/services/llm_gateway.py`, `agent/services/litellm_gateway.py` (lazy-imports litellm, `:31`), `agent/services/airllm_runner.py`, and `agent/services/inference_router.py` are four overlapping backends/routers. Whether all paths are reachable and tested in the default local profile is unclear from the code; this is surface area to verify for dead/redundant paths.

## Data Risks

**Two stores, one system-of-record, manual coupling:**
- Issue: SQLite `layla.db` is the system-of-record (`agent/layla/memory/db_connection.py:20-21`), while embeddings live in a *separate* Chroma store at `CHROMA_PATH` (`agent/layla/memory/vector_store.py:167/212/370`). The Chroma layer reaches back into SQLite by lazy-import (`vector_store.py:222`, `:467`, `:579`) to rehydrate learnings by id.
- Impact: Two stores must be kept consistent by hand. There is no shown transactional boundary spanning both; a write that lands in SQLite but fails to embed (or vice-versa), or a restore of one store but not the other, leaves the vector index and the record-of-truth divergent. Backup (`agent/services/db_backup.py`) and any erasure path must cover *both* stores or risk orphaned embeddings / dangling references — verify coupling.

**Secrets at rest:**
- Bearer/API tokens are config-resident: `agent/config_schema.py:262` describes a remote bearer token stored "via UI or edit runtime_config.json"; `agent/services/tunnel_auth.py` hashes the active token (`:44`) but still supports a *legacy plaintext* `remote_api_key` fallback (`:9`, `:60`, `:80`, `:110`) and `agent/services/auth.py:99` carries the same deprecated plaintext path. `agent/schemas/entity.py:57` notes sensitive data should be "encrypted at rest ideally" — i.e., aspirational, not enforced.
- Impact: A plaintext token path persists for backward compat; sensitive entity content is not guaranteed encrypted at rest.

## Coupling / Layering

**Frontend `window.*` global coupling:**
- Issue: The web UI (`agent/ui/js/`) wires modules together through ~20+ shared `window.*` globals rather than imports/modules: `window.showToast` (37 refs), `window.currentAspect` (25), `window.laylaChatFSM` (23), `window.LaylaUI` (23), `window.currentConversationId` (13), `window.escapeHtml` (13), plus state flags like `window._ttsEnabled`, `window._aspectLocked`, `window._laylaSendBusy`.
- Files: `agent/ui/js/layla-app.js` (736), `agent/ui/js/layla-chat-render.js` (926), `agent/ui/js/layla-workspace.js` (779), `agent/ui/index.html` (1139 — much logic inline).
- Impact: Cross-file load-order dependencies and shared mutable global state; no module boundaries make UI behavior hard to trace and easy to break by reordering scripts.

## Testing / Verifiability Gaps

**Real local inference is never exercised in CI:**
- Issue: CI (`.github/workflows/ci.yml`) runs `pytest` against a stub model — `model_filename = 'ci-stub.gguf'`, `n_gpu_layers = 0` — and explicitly deselects the real-inference/GPU marks: `-m "not slow and not e2e_ui and not browser_smoke and not voice_smoke and not gpu_smoke and not endpoint"`. The only real-model test, `agent/tests/integration_smoke/test_gpu_smoke.py`, is gated behind `gpu_smoke` and not run.
- Impact: 210 test files exercise routing/orchestration logic, but the actual `create_completion` path through `llm_gateway`/`inference_router` is unverified by automation. Regressions in the real generation path (the product's core function) would not be caught in CI; they depend on manual local runs.

**Local-run friction (verifiability):**
- Per project memory, the app requires Python 3.12 and cannot be run on the current host (3.14, no venv); `.pyc` artifacts under `agent/tests/.../__pycache__/...cpython-314.pyc` confirm a 3.14 interpreter has touched the tree. Changes here are typically verified statically, not by running the agent.

## Packaging / Licensing / Ops

**Non-commercial license:**
- `LICENSE` is the "Layla Non-Commercial Source License" (header line 1); `pyproject.toml` classifies as "License :: Free for non-commercial use". This is not an OSI-approved open-source license — it restricts commercial use and downstream redistribution assumptions. Any dependency-style reuse or contribution flow must account for this.

**Bundled native engine:**
- `llama.cpp` is vendored at repo root (directory present). This couples the repo to a specific upstream snapshot and inflates clone/build size; provenance and update cadence of the vendored copy are an ops concern.

**Many root-level scripts / docs:**
- The repo root carries a large set of operational entrypoints (`INSTALL.bat`, `START.bat`, `install.ps1/.sh`, `start-layla.ps1`, `PASTE-AND-RUN.ps1`, `launcher.py`, `layla.py`, `start.sh`) and ~25 top-level Markdown planning/spec docs. Multiple overlapping start paths (`launcher.py` vs `layla.py` vs `start.sh` vs `START.bat`) increase the chance of drift between documented and actual launch behavior.

## Fragile Areas

**Memory subsystem (`agent/layla/memory/`):**
- Why fragile: SQLite system-of-record + hand-rolled 1362-line migration ladder (`migrations.py`) + a 1410-line Chroma layer that lazy-imports back into SQLite. Schema changes must thread the migration ladder, the SQLite accessors, and the embedding rehydration paths simultaneously.
- Safe modification: Treat SQLite and Chroma as a coupled pair; never change one store's shape without the migration ladder and the `vector_store.py` rehydration queries.

**Inference/locking layer (`agent/services/llm_gateway.py`, `inference_router.py`):**
- Why fragile: Three lock types coexist — RLock shim (`llm_gateway.py:69`), global generation `Lock` (`:76`), per-workspace RLocks (`:78`) — passed around as `_llm_lock` parameters (`inference_router.py:100/194/263/379/555`). A wrong lock at a call site risks either a deadlock or two concurrent local generations (the exact thing the design forbids).

---

*Concerns audit: 2026-06-29*
