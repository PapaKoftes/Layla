# Project State

**Project:** Layla — local-first AI agent platform
**Milestone:** Remediate, then Build (v1)
**Updated:** 2026-06-29

## Position in the GSD loop

```
map-codebase ✅ → new-project ✅ → [plan-phase] → execute-phase → verify → ship
                                    ▲ Phase 1 SHIPPED · next: plan Phase 2
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
| 2 | Legal & launch safety | ~ (AGPL+reload done; THIRD_PARTY open) |
| 3 | Verifiable core / CI | open — **de-risked by research** (stories260K + CPU wheel) |
| 4 | Answer-quality eval | open (depends on P3) |
| 5 | Inference reliability | ~ (model-cache bound done) |
| 6 | Data durability & privacy | open |
| 7 | Config consolidation | open |
| 8 | Agent-loop decomposition | open (depends on P3 test net) |
| 9 | Then build (model browser, /v1, install) | open |
| 10 | Frontend & docs cleanup | open |

## Next action
`/gsd-plan-phase 2` — Legal & launch safety. Mostly done (AGPL removed, reload-off); the remaining work is REQ-02's open item: a `THIRD_PARTY`/`NOTICE` file from a dependency-license scan + a CI guard against newly-introduced copyleft deps. No 3.12 runtime needed.

## Key context for any session
- Runtime caveat: this box has Python 3.14; Layla needs 3.11/3.12. Pure-stdlib tests run here; the full app/inference does not (`scripts/setup_test_env.ps1` for a 3.12 venv).
- Verify against implementation, not docs. Every fix gets a runnable test where possible.
- Phases 3/4/8 need the 3.12 runtime + a model; Phases 1/2/5/6/7/9/10 are largely doable without it.
