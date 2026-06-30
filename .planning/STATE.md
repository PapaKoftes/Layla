# Project State

**Project:** Layla — **companion-first** living experience; personalities = domain kits (coding second). See `UNIFIED-ROADMAP.md`.
**Updated:** 2026-06-29

## WHERE WE ARE — ✅ UNITE COMPLETE (+ codebase re-mapped 2026-06-30)
Codebase map refreshed for united+Castilla (`.planning/codebase/`, 7 docs). End-to-end review + the
common-sense path to a watertight, installable product with the Warframe-mystic GUI: **`.planning/WATERTIGHT-PLAN.md`**.
Do-now: (1) wire real-inference CI smoke, (2) **expand the existing modular UI** to the aesthetic + full
see/control surface (NOT a rebuild), (3) low-end guardrails. Deferred (safe debt): ~207 shims, dual config.

## (status) UNITE COMPLETE
**master = the unified tree (refactor + this session), 2143 tests green, landed 2026-06-30.** Next: the **Castilla release** (Spanish bilingual, tuned to the friend's i7-7700HQ/16GB/~26GB-free laptop).

## (history) WHERE WE WERE (pre-unite)
**≈ 5/15 phases fully done · 6/15 partial · 4/15 open · weighted ≈ 8/15** — but that 5/15 is **split across two un-merged branches** (refactor on `master`, this session on `friend-ready-session`). **The gating task is the integration merge** (25 conflicts, `HANDOFF.md §6a`); only after it does `master` actually reflect 5/15. Full breakdown: `UNIFIED-ROADMAP.md`.

```
map ✅ → new-project ✅ → TWO parallel lines reconciled:
   master (refactor)        : arch decomposition + frontend modular + companion VISION  (~2/15 + partials)
   friend-ready-session     : security + compiler-free runtime + kit + benchmark + install (~3/15 + partials)
   ▶ NEXT (gating): MERGE friend-ready-session onto master → true ~5/15 base, then continue companion-first.
```

## Runtime is now LIVE (the old caveat is resolved)
- **Python 3.12.10 installed**; `.venv-test` built with `[dev]` + `[core,llm]` (minus chromadb) + `torch` CPU.
- **Real inference works**: Qwen2.5-Coder-7B-Q4 loads and generates. The dev box **= the friend's tier** (4-core / 16GB / no-GPU), so all measurements transfer.
- **Full test suite runs on 3.12** (was limited to a stdlib subset on the 3.14 box).
- Models on disk: `models/Qwen2.5-Coder-7B-Instruct-Q4_K_M.gguf`, `models/SmolLM2-360M-Instruct-Q4_K_M.gguf` (gitignored).

## Measured truths (drive all decisions)
- 7B-Q4 ≈ **5 tok/s** on this CPU tier; **memory-bandwidth-bound** (thread tuning didn't help).
- Quality: **good for focused edits/refactors**, weaker on from-scratch self-verification (caught a real bug in its own doctest).
- **Speculative decoding is unhelpful on CPU** (prompt-lookup measured *slower*: 1.6 vs 2.6 tok/s).
- → "Best possible local coding" = best *responsive* model (7B) + scaffolding, not the biggest that fits.

## Milestone 1 (remediation) — phase status
| # | Phase | Status |
|---|---|---|
| 1 | Security finish (REQ-10/11/12) | ✅ DONE (58 tests) |
| 2 | Legal & launch (REQ-02) | ✅ DONE (copyleft guard; 11 tests) |
| 3 | Verifiable core / CI | open — **now unblocked** (3.12 env + real models exist) |
| 4 | Answer-quality eval | open (pairs with A5 benchmark) |
| 5 | Inference reliability | ~ (model-cache bound done) |
| 6 | Data durability & privacy | ~ (log redaction done; Chroma items need runtime — now available) |
| 7 | Config consolidation | open |
| 8 | Agent-loop decomposition | open |
| 9–10 | Then-build / frontend | superseded/merged into Milestone 2 |

## Milestone 2 (Friend-Ready) — track status
| Track | Item | Status |
|---|---|---|
| A | A1 stack+model+inference proven | ✅ DONE (REQ-70) |
| A | A2 hardware→kit recommender | ✅ DONE (REQ-71; b306047, 9 tests) |
| A | A3 compiler-less install (chromadb/torch) | 🟡 **torch ✅ + chromadb-free memory fallback ✅** (b… ; 12+87 tests). Fresh-box one-command install path remains. |
| A | A4 onboarding startup sequence | ⏭ wires recommend_kit into first_run |
| A | A5 HumanEval/MBPP benchmark harness | ⏭ |
| A | A6 full-app E2E + one-command install | ⏭ |
| A | A7 per-domain kit contents | ⏭ |
| A | A8 coding-quality scaffolding (repo-map, diff-edits, GBNF, codebase RAG, KV cache) | ⏭ **the real quality lever** |
| A | A9 ecosystem seam (/v1 backend) + character-card portability | ⏭ |
| A | A10 kit upgrades (embedding selection, IQ-quants, benchmark-driven choice) | ⏭ |
| B | B1 ui-next Vite+React foundation (Warframe-mystic) | ⏭ Node ready; aesthetic locked |
| B | B2 core chat · B3 aspect creator · B4 intake quiz · B5 polish | ⏭ |

## Verified state (real stack)
- **Full suite green on the real 3.12 stack: 1734 passed, 0 failed, 10 skipped** (under canonical CI exclusions). The llama-cpp hang is FIXED (conftest default-protects real-Llama tests; opt in with `LAYLA_TEST_REAL_LLM`). Fixed a stale REQ-10/11 allowlist test that encoded the old XFF-localhost bypass.
- **Coding quality is now a NUMBER**: Qwen2.5-Coder-7B = **100% pass@1 (10/10), 3.17 tok/s** on the friend's tier (`benchmarks/`, `scripts/benchmark_coding.py`, 8 tests). Curated easy-to-medium set → strong fundamentals, not saturated; HumanEval-164 is the next discriminating step.

## Known issues (minor, follow-ups)
- Local-only: `_TESTCLIENT_FILES` hang on `.venv-test` due to an httpx/starlette TestClient version mismatch ("install httpx2" deprecation). They are CI-skipped already; pin/upgrade httpx as a Phase 12 follow-up so they run locally too.

## Next action
**Track A first:** A3 (compiler-less `chromadb`/`torch` install — the blocker for "she can install it"), then A4 (onboarding wires `recommend_kit`) and A5 (benchmark). **Track B in parallel:** B1 (`ui-next/` scaffold + design tokens in the locked Warframe-mystic palette). The remediation Phase 3 (verifiable core) is now unblocked and should fold into A5/A6.

## Key context for any session
- The dev box now mirrors the target user (4-core/16GB/no-GPU) — measure here, it transfers.
- Verify against implementation, not docs; report measurements honestly even when they contradict earlier claims (e.g. spec-decoding).
- UI work must not require backend rewrites beyond additive endpoints; the API is the contract.
- Commit cadence: feature commits separate from `docs(planning)` bookkeeping; end messages with the Co-Authored-By trailer.
