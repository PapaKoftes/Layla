# Phase 11 Verification: Local-coding foundation

**Status:** ~ MOSTLY COMPLETE (3 of 4 criteria) · **Date:** 2026-06-29 · **Requirements:** REQ-70, REQ-71, REQ-72

Executed directly on a real 3.12 venv (`.venv-test`) that mirrors the friend's tier (4-core / 16GB / no-GPU), so every measurement transfers.

## Success criteria → evidence

| # | Criterion | Result | Evidence |
|---|---|---|---|
| 1 | Real coding model runs E2E; perf/quality **measured** | ✅ | Qwen2.5-Coder-7B-Q4 loads + generates. Measured: **~5 tok/s** (memory-bandwidth-bound; thread tuning didn't help); good on focused edits, weak on from-scratch self-verify (caught a bug in its own doctest); **speculative decoding measured *slower* on CPU** (1.6 vs 2.6 tok/s). |
| 2 | `recommend_kit` picks best **usable** model + affinity aspect | ✅ | `install/model_selector.recommend_kit` — CPU usability ceiling (refuses the 14B that merely fits), priority-aware, maps domain→aspect, GPU-only draft. Commit b306047, fix 42d5769. **9 tests.** |
| 3 | Memory/RAG works with **no chromadb / no C++ toolchain** | ✅ | `layla/memory/fallback_store.py` (SQLite+NumPy drop-in for the Chroma Collection API); `vector_store` routes both collections through it when chromadb absent; guards run on `_vector_enabled()`. Verified: `add_vector`+`search_similar` return correct NN with chromadb absent. Commit 2fe7e18. **12 + 87 memory tests.** |
| 4 | One-command fresh-box install path | ❌ open | The remaining A3 slice — carries to Phase 13/15 (onboarding + install packaging). |

## Test evidence
- `test_model_kit.py` (9), `test_fallback_store.py` (12), 87 memory/vector tests — all green on 3.12. `test_check_copyleft.py`/`test_secret_store.py`/`test_trust_boundary.py` unaffected.

## Honest gaps surfaced by running it (not yet fixed here)
- **Full suite hangs on the real stack**: `services.llm_gateway.run_completion` retry-sleeps once llama-cpp is installed. → **Phase 12, criterion 1.**
- `torch` CPU wheel installs; `chromadb` does **not** build (no compiler) — handled by the fallback, but the "real chromadb optional-install" path and the one-command installer remain.

## Carry-forward
- REQ-72 install-path slice → Phase 13/15.
- Suite-hang → Phase 12.
