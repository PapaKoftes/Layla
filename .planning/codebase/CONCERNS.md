# Codebase Concerns

**Analysis Date:** 2026-06-30

> Re-assessed after the large service-layer refactor and the v1.4.0 "Castilla" release. The prior CONCERNS.md (2026-06-29) predated this work; several items it flagged are now **resolved** and are recorded as such below so they are not re-litigated. File:line evidence is given where load-bearing.

## Resolved Since Last Audit (do not re-flag)

**Trust-boundary remote auth (REQ-10/11/12) — DONE.**
- Hardened auth lives at `agent/services/safety/auth.py`. Forwarding headers (`cf-connecting-ip`, `x-forwarded-for`, `forwarded`, ...) are honored *only* on loopback (the tunnel terminus), with provider-overwrite headers trusted first and rightmost-trusted-hop XFF parsing (`auth.py:143-187`). `require_auth_always` (REQ-11) is tri-state and defaults to "require token whenever `remote_enabled`", closing the ssh-R/socat header-stripping-forwarder class (`auth.py:190-209`). `is_direct_local` replaces bare host checks for "trust the local caller" decisions (`auth.py:212-222`). Tunnel auth (hashed token + IP allowlist + expiry) is in `agent/services/governance/tunnel_auth.py`.
- **Residual:** a *deprecated plaintext* `remote_api_key` fallback still exists for backward compat (`auth.py:46-54`, logs a warning). Low severity — it is opt-in legacy config — but it should be removed on a future breaking release.

**Copyleft guard (REQ-02) — DONE.** `scripts/check_copyleft.py` scans installed distribution metadata and fails CI on strong-copyleft (AGPL/GPL/SSPL) deps, reasoning over structured SPDX/trove metadata to avoid false positives. Wired into CI (`.github/workflows/ci.yml:39-40`). PyMuPDF/`fitz` is gone (no refs in `pyproject.toml`).

**`agent_loop.py` god-module — RESOLVED.** The 4119-line monolith is now **910 lines** (`agent/agent_loop.py`). Cohesive concerns were extracted into `agent/services/agent/` (`ux_emitter.py`, `verification_engine.py`, `tool_guards.py`, `tool_helpers.py`) plus `agent/services/infrastructure/agent_loop_formatting.py`.

**Frontend `window.*` global coupling — LARGELY RESOLVED.** The flat `agent/ui/js/*.js` files are gone. The UI is now an ES-module tree: `agent/ui/core/` (`bus.js`, `state.js`, `actions.js`, `overlay.js`) + 28 feature modules in `agent/ui/components/` using real `import`/`export` (33 files). Remaining `window.*` use is consolidated into an explicit, documented compat bridge (`agent/ui/core/compat.js`) — ~140 shims already removed; only cross-module calls and dynamic-onclick handlers remain. Now a *clarity* concern (see Tech Debt), not a structural one.

## Tech Debt

**Backward-compat shim surface (~207 flat modules) — HIGH (clarity/maintenance):**
- Issue: The refactor re-homed all services into subpackages (`agent/services/{safety,governance,llm,memory,infrastructure,planning,tools,...}/`), but left **207 flat `agent/services/*.py` shims** that just re-export the real module. Each is a 6-line `importlib`/`sys.modules` redirect (e.g. `agent/services/auth.py` → `services.safety.auth`; `agent/services/config_cache.py` → `services.infrastructure.config_cache`).
- Files: `agent/services/*.py` (207 files), real code under `agent/services/<domain>/`.
- Impact: Two import paths exist for every service. A reader can't tell from `from services.auth import ...` whether they're hitting the shim or the canonical module; grep/IDE navigation lands on a redirect first. This is the explicitly-flagged debt (ADR + VISION Phase 10 "reduce shim surface").
- Fix approach: Phased removal — migrate importers to the canonical `services.<domain>.<mod>` path, then delete the flat shim. The shims make this safe to do incrementally.

**Two config files / two loaders persist — MEDIUM:**
- Issue: `config_cache` was de-duplicated to a *single* loader (`agent/services/infrastructure/config_cache.py:1` "Single-source config.json loader"), so the prior "two config_cache implementations" concern is gone. **But it still reads `config.json`** (`_CFG_PATH = .../config.json`, `:6`), a *different file* from the real system-of-record `runtime_config.json` loaded by `runtime_safety.load_config()` (`agent/runtime_safety.py:55-56`). Both files + caches coexist; `agent/runtime_config.json` is present on disk.
- Files: `agent/services/infrastructure/config_cache.py:6`, `agent/runtime_safety.py:55`.
- Impact: Two JSON files with independent caches/invalidation. A `cfg.get("x")` call site doesn't reveal which file is authoritative; the two can drift.
- Fix approach: Collapse to one loader/file; if `config.json` is legacy, document and remove. (~78 modules still import `config_cache`.)

**Remaining complexity hotspots:**
- `agent/layla/memory/vector_store.py` (~1410), `agent/layla/memory/migrations.py` (~1362 hand-rolled migration ladder), `cursor-layla-mcp/server.py` (~1296), `agent/services/tool_dispatch.py`, `agent/layla/tools/impl/file_ops.py`, `agent/routers/agent.py` remain large single-file domains. Lower priority than before but still god-modules.

**Redundant inference backends:**
- `agent/services/llm/` carries four overlapping backends/routers: `llm_gateway.py`, `litellm_gateway.py`, `airllm_runner.py`, `inference_router.py` (plus `model_router.py`). Whether every path is reachable/tested in the default local profile is unverified — surface area to audit for dead paths.

## Performance & Scale

**Inference throughput is the central ceiling — MEDIUM (inherent, mitigated):**
- Reality: a 7B-Q4 model runs ≈ 3–5 tok/s on a CPU laptop — acceptable but not snappy. This is hardware-bound, not a bug.
- Single in-flight generation: `llm_generation_lock = threading.Lock()` (`agent/services/llm/llm_gateway.py:77`) serializes all local `create_completion` calls so two workspaces never generate concurrently. A legacy `_llm_lock` (RLock) is aliased as `llm_serialize_lock` (`:71-73`) and imported by the agent loop; per-workspace RLocks (`get_agent_serialize_lock`, `:83`) layer on top but all funnel through the one generation lock (`:792`).
- Memory-bound model cache: at most 2 resident GGUF models (`_DEFAULT_MAX_RESIDENT_MODELS = 2`, `:23`), with eviction via `_evict_models_if_needed` (`:36`, called `:572`). `ResourceGovernor` mitigates contention but cannot lift the memory ceiling.
- Impact: Throughput is bounded to one in-flight local generation per process. A hung generation holding `llm_generation_lock` stalls every workspace. Correct for memory safety, but the system's scalability ceiling.
- Mitigation path: this is inherent to single-process local llama_cpp; horizontal scale would require a separate inference worker process. Document as a known constraint, not a quick fix.

**Fragile lock layering:**
- Three lock types coexist in `agent/services/llm/llm_gateway.py`: RLock shim (`:71`), global `Lock` (`:77`), per-workspace RLocks (`:83`), selected by config at `:792` (`infer_lock = llm_generation_lock if cfg.get("llm_serialize_per_workspace") else llm_serialize_lock`). A wrong lock at a call site risks either deadlock or two concurrent local generations (the exact thing forbidden).

## Data Risks

**Two stores, manual coupling:** SQLite `layla.db` is the system-of-record while embeddings live in a separate Chroma store; `agent/layla/memory/vector_store.py` lazy-imports back into the SQLite layer to rehydrate by id. No shown transactional boundary spans both — a write landing in SQLite but failing to embed (or a restore of one store but not the other) leaves the vector index and record-of-truth divergent. Backup and any erasure/delete path must cover *both* stores.

## Testing / Verifiability Gaps

**Real local inference is never exercised in CI — HIGH:**
- CI runs `pytest` against a stub model and deselects real-inference marks: `-m "not slow and not e2e_ui and not browser_smoke and not voice_smoke and not gpu_smoke and not endpoint"` (`.github/workflows/ci.yml:71`, `:127`).
- An inference-smoke *seam* exists — `LAYLA_TEST_REAL_LLM` gates real-model tests (`agent/tests/conftest.py:65`), and a Playwright `e2e-ui` job exists (`:129-174`) — **but no CI job sets `LAYLA_TEST_REAL_LLM`** (no occurrences under `.github/`). The actual `create_completion` path (the product's core function) is unverified by automation; regressions depend on manual local runs.
- Fix approach: wire an opt-in CI job (or scheduled job) that sets `LAYLA_TEST_REAL_LLM=1` with a small real GGUF, accepting longer runtime.

**`_TESTCLIENT_FILES` skipped — local hang risk:**
- `agent/tests/conftest.py:17-26` lists TestClient/lifespan tests (`test_remote.py`, `test_tool_tracing.py`, `test_meilisearch_bridge.py`, ...) that are `collect_ignore`d under `CI` because the app lifespan hangs with no model/scheduler/DB (`conftest.py:13-15`). The comment claims they "run fine locally," but per project memory the app can't run on the current host (Python 3.14 vs required 3.12, no venv) — so locally these would *hang*, not pass. Effectively these tests run nowhere in this environment.

**Local-run friction:** Python 3.12 required; current host is 3.14 with no venv (`.pyc` artifacts confirm a 3.14 interpreter has touched the tree). Changes are verified statically, not by running the agent.

## Product Gaps Toward "Watertight Installable Product"

**No automated full-app E2E gate on the real path — HIGH:** as above, the real-inference seam (`LAYLA_TEST_REAL_LLM`) and the Playwright `e2e-ui` job exist but the real-LLM smoke is unwired. There is no green-on-every-PR signal that a fresh install can actually load a model and complete a turn.

**Castilla GUI aesthetic not yet applied to the modular UI — MEDIUM:** the UI was refactored into ES modules (`agent/ui/core/` + `agent/ui/components/`), but the intended Warframe-mystic aesthetic and full control surface are not yet built out across the now-modular components. Visual/feature parity work remains; the modular structure makes it tractable.

**Creative aspect (`eris`) model sizing — LOW (verify):** the `eris` personality exists (`personalities/eris.json`) but carries **no model-tier/size field** in its JSON — the "maps to an 11B, too big for low-end" claim is a product-intent note not encoded in config. If aspect→model mapping is intended, it must be made explicit and gated by hardware tier so a low-end install doesn't try to load an 11B. Currently unenforced in the personality data.

## Packaging / Licensing / Ops

**Non-commercial license:** `LICENSE` is the "Layla Non-Commercial Source License"; `pyproject.toml` classifies "Free for non-commercial use" — not OSI-approved. Any reuse/contribution flow must account for this. (The copyleft guard above exists precisely because this proprietary license is incompatible with strong copyleft.)

**Many root-level entrypoints / docs:** the repo root carries multiple overlapping start paths (`launcher.py`, `layla.py`, `start.sh`, `START.bat`, `start-layla.ps1`, `PASTE-AND-RUN.ps1`, `install.ps1/.sh`, `INSTALL.bat`) plus ~30 top-level Markdown planning/spec docs. Risk of drift between documented and actual launch behavior.

## Priority Summary

| Severity | Concern |
|----------|---------|
| HIGH | Real inference path unverified in CI; `LAYLA_TEST_REAL_LLM` smoke job unwired |
| HIGH | ~207 flat service shims — dual import paths, navigation/clarity debt |
| MEDIUM | Two config files (`config.json` vs `runtime_config.json`) / two loaders |
| MEDIUM | Single-process / one-model / global-generation-lock scalability ceiling |
| MEDIUM | Castilla GUI aesthetic + full control surface not yet applied to modular UI |
| MEDIUM | Remaining god-modules (vector_store, migrations, tool_dispatch, MCP server) |
| LOW | Deprecated plaintext `remote_api_key` fallback still present |
| LOW | `eris`→11B mapping is intent, not enforced/hardware-gated in config |
| LOW | Two-store (SQLite + Chroma) manual consistency; non-commercial license; root entrypoint sprawl |

---

*Concerns audit: 2026-06-30 (post-refactor / Castilla re-assessment)*
