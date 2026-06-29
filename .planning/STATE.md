# Project State

**Project:** Layla — local-first AI agent platform
**Milestone:** Remediate, then Build (v1)
**Updated:** 2026-06-29

## Position in the GSD loop

```
map-codebase ✅ → new-project ✅ → [plan-phase] → execute-phase → verify → ship
                                    ▲ Phases 1+2 SHIPPED · next: Phase 5/6/7 (3.12-free)
```

GSD init is complete. No phase is active yet.

## Planning artifacts (all on `master`)
- `PROJECT.md` — context + direction (remediate-then-build).
- `config.json` — Balanced model profile, research on, Standard granularity.
- `codebase/` — 7 clean-room map docs (native `gsd-codebase-mapper`).
- `research/` — 4 briefs + `SUMMARY.md` (ecosystem, CI/LLM-testing, eval, security).
- `REQUIREMENTS.md` — REQ-01..04 (done), REQ-10..63 (active).
- `ROADMAP.md` — 10 phases, blast-radius ordered, REQ coverage validated.

## Phase status
| # | Phase | Status |
|---|---|---|
| 1 | Security finish (REQ-10/11/12) | ✅ DONE (4f05229, b1968ad, 77335b4; 58 tests) |
| 2 | Legal & launch safety (REQ-02) | ✅ DONE (copyleft CI guard + THIRD_PARTY; 11 tests) |
| 3 | Verifiable core / CI | open — **de-risked by research** (stories260K + CPU wheel) |
| 4 | Answer-quality eval | open (depends on P3) |
| 5 | Inference reliability | ~ (model-cache bound done) |
| 6 | Data durability & privacy (REQ-42/43) | ~ (log redaction done; Chroma backup/erasure need runtime) |
| 7 | Config consolidation | open |
| 8 | Agent-loop decomposition | open (depends on P3 test net) |
| 9 | Then build (model browser, /v1, install) | open |
| 10 | Frontend & docs cleanup | open |

## Next action
Phases 1 & 2 shipped. Phases 3/4/8 need the 3.12 runtime + a model (`scripts/setup_test_env.ps1`), so on this 3.14 box the next runnable work is one of:
- **Phase 6 — Data durability & privacy** (SQLite WAL/atomic-write/backup, secret redaction in logs) — mostly stdlib-testable.
- **Phase 7 — Config consolidation** (single source of truth for runtime config; pure-Python, testable).
- **Phase 5 — Inference reliability** (model-cache bound done; remaining items partly need the runtime).
Pick Phase 6 or 7 next; Phase 3 (verifiable core) is the highest-value but is gated on standing up the 3.12 venv + `stories260K.gguf`.

## Key context for any session
- Runtime caveat: this box has Python 3.14; Layla needs 3.11/3.12. Pure-stdlib tests run here; the full app/inference does not (`scripts/setup_test_env.ps1` for a 3.12 venv).
- Verify against implementation, not docs. Every fix gets a runnable test where possible.
- Phases 3/4/8 need the 3.12 runtime + a model; Phases 1/2/5/6/7/9/10 are largely doable without it.
