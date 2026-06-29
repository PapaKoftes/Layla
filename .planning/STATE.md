# Project State

**Project:** Layla — local-first AI agent platform
**Milestones:** (1) Remediate-then-Build substrate · (2) **Friend-Ready** product (North Star)
**Updated:** 2026-06-29

## Position in the GSD loop

```
map-codebase ✅ → new-project ✅ → plan/execute (remediation P1-2 ✅, P6 partial) ✅
                          → Milestone 2 "Friend-Ready" PLANNED → executing Track A
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

## Known issues (found by actually running it)
- **Full suite hangs on the real stack**: a `services.llm_gateway.run_completion` test sits in `time.sleep(backoff)` retry-looping once llama-cpp is installed (previously skipped). Must make that test not attempt real completion (mock/seam). Until fixed, the "full green suite on the real stack" claim is unverified — run targeted subsets.

## Next action
**Track A first:** A3 (compiler-less `chromadb`/`torch` install — the blocker for "she can install it"), then A4 (onboarding wires `recommend_kit`) and A5 (benchmark). **Track B in parallel:** B1 (`ui-next/` scaffold + design tokens in the locked Warframe-mystic palette). The remediation Phase 3 (verifiable core) is now unblocked and should fold into A5/A6.

## Key context for any session
- The dev box now mirrors the target user (4-core/16GB/no-GPU) — measure here, it transfers.
- Verify against implementation, not docs; report measurements honestly even when they contradict earlier claims (e.g. spec-decoding).
- UI work must not require backend rewrites beyond additive endpoints; the API is the contract.
- Commit cadence: feature commits separate from `docs(planning)` bookkeeping; end messages with the Co-Authored-By trailer.
