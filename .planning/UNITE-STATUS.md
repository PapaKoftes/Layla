# Unite Status — merge of friend-ready-session onto the refactor

**Date:** 2026-06-30 · **Branch:** `integration` (local) → pushed to `origin/unite-integration`. **`master` is UNTOUCHED** (the refactor) until the suite is 100% green.

## Done & verified
- **Structural merge complete**: refactor (origin/master) + this session's 56 commits. 25 conflicts resolved (UI + non-critical backend → refactor; new files auto-merged; runtime_safety/pyproject → union; moved files → refactor shims).
- **Security re-homed + verified (100/100 security tests)**: REQ-10/11 trust boundary into `services/safety/auth.py`; removed the localhost-bypass the refactor still carried in `services/governance/tunnel_auth.py` (REQ-10).
- **Batch A fixed (3 tests)**: re-homed `delete_user_identity`; fixed shell-gate test to the new `services/tools/tool_dispatch.py` path + deny-by-default form (`not ctx.allow_run` — security confirmed present); moved `secret_store`/`secret_filter` into `services/safety/` with flat shims (refactor's architecture rule).
- **Suite: 2131+ passed, ~9 failing** (was 12; Batch A fixed 3). pyproject correct (cpu extra, PyMuPDF removed, keyring in core).

## Remaining: 9 failures — all "my feature vs the refactor's replacement" (decide superseded-vs-re-home)
Not security; not structural. Each needs a per-subsystem decision against the refactor's new architecture.

1. **Model cache (4: `test_model_cache_bound.py`)** — my F9 `_llm_by_path` + `_evict_models_if_needed` (OOM bound for multi-model routing). The refactor uses single-`_llm` + `services/resource_manager` + dual-models (line ~296 of `services/llm/llm_gateway.py`). **Decide:** does resource_manager already bound model memory? If yes → update/retire these tests to the refactor's mechanism. If no → re-home `_evict_models_if_needed` + `_llm_by_path` into `services/llm/llm_gateway.py` AND wire the eviction into its real load path (not dead code).

2. **Council (4: `test_council_models.py`)** — my Jun-4 `debate_engine._aspect_model_override` + `_run_aspect_completion` + `llm_gateway.get/set_model_override` (global override). The refactor's `run_completion` takes a **`model_override` param** instead. **Decide:** re-home the global override fns into `services/debate_engine.py` + `services/llm/llm_gateway.py`, OR rewrite the tests/feature to the refactor's param-based override.

3. **Steer (1: `test_shared_state_safety.py::TestSteerHints::test_empty_text_ignored`)** — `pop_one_agent_steer_hint` returned `'msg-5'` instead of `''` after pushing empty/whitespace. Looks like a **test-isolation bleed** (prior test's hint not reset) or the refactor's `push_agent_steer_hint` storing empties. **Decide:** ensure empty/whitespace hints are ignored in `agent/shared_state.py` and/or reset shared-state between tests in conftest.

## Rule
`master` does not move until `CI=1 pytest` is 100% green on `integration`. The integration branch preserves all work; nothing is lost; the refactor `master` is intact.

## To finish (focused pass)
Resolve the 3 subsystems above (re-home or test-update per decision), re-run `CI=1 ../.venv-test/Scripts/python.exe -m pytest -m "not slow and not e2e_ui and not browser_smoke and not voice_smoke and not gpu_smoke and not endpoint"` until green, then `git push origin integration:master` and fast-forward local master.
