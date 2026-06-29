# Roadmap: Layla — Audit Remediation & Hardening

## Overview

Derived from the clean-room codebase map (`.planning/codebase/`) and the adversarial audit (88 verified findings). The journey: first make Layla **safe to expose and legal to ship** (done), then make CI **prove the core works**, then close the **reliability / data / scale** gaps, then pay down **architecture, config, product focus, and docs**. Phases are ordered by blast-radius: security/legal → verifiability → reliability → maintainability/product. `[x]` = completed in remediation work to date; `[ ]` = open.

## Phases

- [x] **Phase 1: Trust-boundary & RCE hardening** - Eliminate the loopback-trust class (tunnel auth, body capability flags, approval gates).
- [~] **Phase 2: Legal & launch safety** - AGPL removal, production-safe launch, license accounting.
- [~] **Phase 3: Make CI prove the core (C4/C5)** - Real inference + agent-loop run in CI; releases gated.
- [ ] **Phase 4: Answer-quality eval harness** - Grounding/regression eval so "quality" is measured, not asserted.
- [~] **Phase 5: Inference reliability & scale** - Remove dead infra, bound memory, surface failures.
- [ ] **Phase 6: Data durability & privacy** - Joint backup, erasure, PII handling, DB maintenance.
- [ ] **Phase 7: Config consolidation** - One typed, documented config schema.
- [ ] **Phase 8: Agent-loop decomposition** - Break the 4,119-line god-file into tested units.
- [ ] **Phase 9: Product focus & onboarding** - Cut sprawl, fix install friction, model browser.
- [ ] **Phase 10: Frontend modularization & docs cleanup** - Kill global coupling; collapse doc drift.

## Phase Details

### Phase 1: Trust-boundary & RCE hardening
**Goal**: A remote (tunnel) caller can never reach unauthenticated RCE or rewrite security config.
**Depends on**: Nothing.
**Success Criteria** (TRUE):
  1. Tunnelled/forwarded requests must authenticate (loopback trusted only when direct + no forwarding header). ✔
  2. `/v1` and `/agent` ignore body `allow_run/allow_write` for non-direct-local callers (fail-closed). ✔
  3. Shell and MCP tools are deny-by-default (approval required unless already allowed). ✔
  4. IP allowlist/rate-limit not spoofable via `X-Forwarded-For`. ✔
**Plans**: complete (commits b6bb9aa, 44cc3b0).
Plans:
- [x] 01-01: Proxy-aware `real_client_ip`/`is_direct_local`; apply at all middlewares + settings + autonomous.
- [x] 01-02: Invert shell + mcp approval gates; force remote body flags false on `/v1` + `/agent`.
- [x] 01-03: Harden XFF trust + drop allowlist loopback short-circuit; tests `test_trust_boundary` / `test_ip_allowlist`.

### Phase 2: Legal & launch safety
**Goal**: The packaged product is legally redistributable and starts in a production-safe mode.
**Depends on**: Nothing.
**Success Criteria** (TRUE):
  1. No copyleft (AGPL) dependency bundled under the proprietary license. ✔ (PyMuPDF removed; pypdf fallback)
  2. Default launch does not run `uvicorn --reload`. ✔
  3. A `THIRD_PARTY`/NOTICE file documents dependency licenses, generated from a license scan. ☐
**Plans**: 1 open.
Plans:
- [x] 02-01: Remove PyMuPDF; reload off by default.
- [ ] 02-02: Dependency license scan + `THIRD_PARTY.md`; CI check for new copyleft deps.

### Phase 3: Make CI prove the core (C4/C5)
**Goal**: Green CI means real inference and the real agent loop actually work.
**Depends on**: A 3.12 test runtime (`scripts/setup_test_env.ps1`).
**Success Criteria** (TRUE):
  1. A CI job loads a tiny real GGUF and runs `run_completion` end-to-end, asserting output properties. ☐
  2. The agent-loop tests are no longer in `collect_ignore` (run with `run_completion` mocked). ☐
  3. `release.yml` is gated on the test job. ☐
  4. The loop's pure decision/gate logic is covered. ✔ (`test_agent_core_logic`)
**Plans**: 3 open.
Plans:
- [x] 03-01: Pure-logic tests for `parse_decision` + completion gate (no model).
- [ ] 03-02: Build/pin a CPU-baseline `llama-cpp-python` wheel for CI; add a tiny-GGUF inference job.
- [ ] 03-03: Narrow `collect_ignore` to only-Llama-constructing files; gate `release.yml` on tests.

### Phase 4: Answer-quality eval harness
**Goal**: Output quality (grounding, correctness, regressions) is measured, not assumed.
**Depends on**: Phase 3 (a runnable model in CI/nightly).
**Success Criteria** (TRUE):
  1. A golden prompt set with scored expectations runs in nightly and reports pass-rate. ☐
  2. RAG answers can be checked for source-grounding (cite-or-abstain) on the golden set. ☐
  3. The completion gate's thresholds are tuned against measured outcomes, not hardcoded guesses. ☐
**Plans**: TBD.
Plans:
- [ ] 04-01: Define a 20–50 prompt golden set + scoring harness.
- [ ] 04-02: Grounding/abstention metric; wire into nightly.

### Phase 5: Inference reliability & scale
**Goal**: No dead infra, bounded memory, and failures are visible.
**Depends on**: Nothing.
**Success Criteria** (TRUE):
  1. Resident GGUF models are bounded (routing can't OOM the process). ✔ (`max_resident_models`)
  2. The unused async `LLMRequestQueue` is removed OR made the single live path (not both). ☐
  3. `save_learning` does not hold the SQLite write txn during embedding. ☐
  4. `/health` reports model-load failure as unhealthy. ☐
**Plans**: 3 open.
Plans:
- [x] 05-01: Bounded model cache (LRU evict non-primary) + tests.
- [ ] 05-02: Delete the dead request queue + its lifespan start (confirm zero callers); document the single-lock model.
- [ ] 05-03: Move embedding outside the write transaction; add model-failure to `/health`.

### Phase 6: Data durability & privacy
**Goal**: SQLite + vectors recover together; user data is erasable and not leaked to logs.
**Depends on**: Nothing.
**Success Criteria** (TRUE):
  1. Backup includes the Chroma vector dir; restore keeps SQLite↔embeddings consistent. ☐
  2. WAL is checkpointed and the DB VACUUMed on a schedule. ☐
  3. Deleting a conversation/learning also removes its vectors (no orphans); identity facts forgettable. ☐ (partial: identity forget done)
  4. Audit/execution logs redact PII/secret argument content. ☐
**Plans**: TBD.

### Phase 7: Config consolidation
**Goal**: One typed, documented source of truth for config.
**Depends on**: Nothing.
**Success Criteria** (TRUE):
  1. All keys are defined/typed/defaulted in one schema (no inlined-default drift). ☐
  2. The settings UI/schema documents every operator-relevant key. ☐
**Plans**: TBD.

### Phase 8: Agent-loop decomposition
**Goal**: The core loop is a set of small, tested units instead of one 1,665-line function.
**Depends on**: Phase 3 (characterization tests) — do NOT refactor without the net.
**Success Criteria** (TRUE):
  1. `_autonomous_run_impl_core` is split into decide/dispatch/verify/recover/emit units with explicit state. ☐
  2. `services/` no longer imports `agent_loop` private internals. ☐
**Plans**: TBD.

### Phase 9: Product focus & onboarding
**Goal**: One clear persona; first-run that can't silently fail; install friction reduced.
**Depends on**: Nothing.
**Success Criteria** (TRUE):
  1. "No model = obviously broken" everywhere; first-run gates on a loaded model. ✔ (banner + skippable quiz)
  2. A built-in model browser/downloader (no manual GGUF + JSON edit). ☐
  3. Niche features (German/Warframe/Discord/pairing) demoted behind an opt-in/plugins fold. ☐
  4. Docs/positioning don't recommend the competitor. ☐
**Plans**: 1 done, rest open.

### Phase 10: Frontend modularization & docs cleanup
**Goal**: Remove global coupling; one source of truth for shared UI data; collapse doc drift.
**Depends on**: Nothing.
**Success Criteria** (TRUE):
  1. Shared data (ASPECTS) defined once; `window.*` global surface reduced behind a namespace/modules. ☐
  2. Top-level docs collapsed to ARCHITECTURE + ROADMAP + CHANGELOG; the rest archived. ☐
**Plans**: TBD.
