# Roadmap: Layla — Remediate, then Build

## Overview

Derived from `.planning/PROJECT.md`, `.planning/REQUIREMENTS.md`, the four research briefs in `.planning/research/`, and the clean-room codebase map (`.planning/codebase/`). Direction: **remediate, then build** — first make Layla *safe to expose, legal to ship, and verifiably correct*, then add new capability on the hardened foundation.

Phases are ordered by **blast-radius**: finish security (Phase 1) → legal/launch (Phase 2, mostly done) → make CI prove the core (Phase 3, now de-risked by research) → measure answer quality (Phase 4) → inference reliability (Phase 5) → data durability (Phase 6) → config consolidation (Phase 7) → agent-loop decomposition (Phase 8, depends on the Phase 3 test net) → then-build product work (Phase 9) → frontend/docs (Phase 10).

Coverage: every **active** requirement (REQ-10..REQ-63) maps to exactly one phase. Validated requirements (REQ-01..REQ-04) are shown against the phase that delivered them and marked `[x]`. `[x]` = done on `master`; `[~]` = partially done; `[ ]` = open.

## Phases

- [x] **Phase 1: Security finish** - Close the residual forwarded-header gap, default auth-always-when-exposed, move secrets to the OS keyring. ✅ DONE (4f05229, b1968ad, 77335b4)
- [~] **Phase 2: Legal & launch safety** - AGPL removed and reload-off shipped; add a dependency-license accounting.
- [ ] **Phase 3: Verifiable core (CI)** - Real tiny-model inference + the real agent loop run every PR; releases gated.
- [ ] **Phase 4: Answer-quality eval harness** - Inline grounding/cite-or-abstain + a promptfoo golden set so quality is measured, not asserted.
- [~] **Phase 5: Inference reliability** - Remove dead queue infra, take embedding out of the write txn, surface model-load failure.
- [ ] **Phase 6: Data durability & privacy** - Joint SQLite+Chroma backup, erasure without orphans, scheduled DB maintenance, PII-safe logs.
- [ ] **Phase 7: Config consolidation** - One typed, documented config schema; kill the second loader.
- [ ] **Phase 8: Agent-loop decomposition** - Break the 4,119-line god-file into tested decide/dispatch/verify/recover/emit units.
- [ ] **Phase 9: Then build** - Hardware-aware model browser, `/v1` param conformance, prebuilt wheels + opt-in ML stack, demoable approval-gating.
- [ ] **Phase 10: Frontend & docs cleanup** - Shared UI data defined once, `window.*` surface reduced, top-level docs collapsed.

## Phase Details

### Phase 1: Security finish
**Goal**: A remote (tunnel) caller cannot poison the allowlist/rate-limiter/audit log via forged forwarded headers, cannot reach an unauthenticated surface when exposed, and provider secrets are not plaintext on disk.
**Depends on**: Nothing (builds directly on the already-remediated trust boundary, REQ-01).
**Requirements**: REQ-10, REQ-11, REQ-12
**Success Criteria** (what must be TRUE):
  1. `real_client_ip` derives the client by a **rightmost-trusted-hop** walk over merged XFF entries, skipping IPs/CIDRs in a configurable `tunnel_trusted_proxies` list; a remote client that prepends a fake XFF entry cannot become a trusted/allowlisted IP. *(security-patterns: replace `auth.py::real_client_ip` `split(",")[0]` leftmost with reverse walk; validate/normalize every derived IP before it touches allowlist/rate-limit/audit)*
  2. When `remote_enabled`, the Bearer token is required even for loopback by default (`remote_require_auth_always` defaults on when exposed); the loopback-exempt path is an explicit opt-out, not the default. *(closes the Ollama "~175k unauthenticated hosts" class one layer in)*
  3. Provider secrets (`tunnel_token_hash`, `*_api_key`, `*_token`, `litellm_api_keys`) resolve from the OS keyring (DPAPI/Keychain/Secret Service via `keyring`) with an env→plaintext fallback; newly-entered secrets are no longer written to `runtime_config.json`.
  4. A test asserts a forged `X-Forwarded-For`/`Cf-Connecting-Ip` from a non-trusted hop does not change the derived client IP used for allowlist/rate-limit decisions.
**Plans**: TBD
**UI hint**: yes

### Phase 2: Legal & launch safety
**Goal**: The packaged product is legally redistributable and starts in a production-safe mode.
**Depends on**: Nothing.
**Requirements**: REQ-02 *(validated — evidence on `master`)*
**Success Criteria** (what must be TRUE):
  1. No copyleft (AGPL) dependency is bundled under the proprietary license. [x] *(PyMuPDF removed; pypdf fallback)*
  2. Default launch does not run `uvicorn --reload`. [x]
  3. A `THIRD_PARTY`/`NOTICE` file documents dependency licenses, generated from a license scan; CI fails on a newly-introduced copyleft dependency. [ ]
**Plans**: TBD

### Phase 3: Verifiable core (CI)
**Goal**: Green CI means the real generation path and the real agent loop actually work — not just mocked orchestration.
**Depends on**: A 3.11/3.12 test runtime (`scripts/setup_test_env.ps1`).
**Requirements**: REQ-20, REQ-21, REQ-22
**Success Criteria** (what must be TRUE):
  1. A blocking `inference-smoke` CI job loads a committed ~1 MB `stories260K.gguf` and drives `services.llm_gateway.run_completion` end-to-end, asserting **structural** properties (dict shape, non-empty text, `len(tokens) <= max_tokens`, stop honored, multi-turn KV-cache coherence) — not exact strings. *(ci-llm-testing: portable CPU binary via `CMAKE_ARGS="-DGGML_NATIVE=OFF -DGGML_AVX512=OFF"` or the abetlen CPU wheel index; `tiny_llm` fixture; cache/commit the 1 MB model)*
  2. The agent-loop tests (`test_agent_loop.py`, `test_completion.py`, `test_engineering_pipeline.py`, …) are no longer `collect_ignore`d on CI: each is audited file-by-file and converted to the `mock_llm`/scripted-sequence fixture, so `_LLAMA_CPP_FILES` shrinks to only files that genuinely construct a real `Llama`.
  3. `run_completion` threads `seed`/`top_k` through to `inference_router` so the smoke job can assert deterministically (`seed=42`, `top_k=1`, `n_threads=1`).
  4. `release.yml` is gated on the `test` + `inference-smoke` jobs; a red core test blocks a release.
  5. The loop's pure decision/gate logic remains covered. [x] *(REQ-03, `test_agent_core_logic.py`)*
**Plans**: TBD

### Phase 4: Answer-quality eval harness
**Goal**: Output quality (grounding, correctness, regressions) is measured offline with no cloud judge, not assumed.
**Depends on**: Phase 3 (a runnable real model in CI/nightly).
**Requirements**: REQ-30, REQ-31
**Success Criteria** (what must be TRUE):
  1. A new `agent/services/grounding_eval.py` runs an inline MiniCheck/NLI (flan-t5-large, 770M, CPU) check over answer sentences vs. retrieved context at the `try_chroma_retrieval` seam, emits a structured `grounding` block (`faithfulness`, `relevancy`, `unsupported_claims`, `grounding_pass`), and supports cite-or-abstain. *(eval-harness)*
  2. The check is wired into `passes_completion_gate` behind a `grounding_eval_enabled` flag: observe-only first, then **hard-gate only on a clear threshold breach for retrieval answers** (`ungrounded(score=…)` / `non_responsive`); non-RAG answers are unaffected.
  3. A 20–50 prompt golden set runs via promptfoo against Layla's local GGUF endpoint on PR + nightly, with per-test thresholds and a non-zero exit on regression; deterministic + `python:`(MiniCheck) + `similar` asserts, sparing local `llm-rubric`.
  4. Unit tests extend `test_completion_gate.py` to cover the grounding metrics and the abstention path.
**Plans**: TBD

### Phase 5: Inference reliability
**Goal**: No dead inference infra, no lock held across embedding, and model-load failure is visible.
**Depends on**: Nothing.
**Requirements**: REQ-40, REQ-41
**Success Criteria** (what must be TRUE):
  1. The unused async `LLMRequestQueue` is removed (or made the single live path — not both), zero callers confirmed, and the single-process/single-model/one-global-lock concurrency model is documented honestly. *(CONCERNS: `llm_gateway.py` lock layering; four overlapping backends)*
  2. `save_learning` no longer holds the SQLite write transaction while embedding (embedding moved outside the txn).
  3. `/health` reports a model-load failure as **unhealthy** rather than masking it.
  4. Resident GGUF models stay bounded so routing cannot OOM the process. [x] *(REQ-04, `max_resident_models`)*
**Plans**: TBD

### Phase 6: Data durability & privacy
**Goal**: SQLite and the Chroma vectors recover together; deleting data leaves no orphaned vectors; logs do not leak PII/secrets.
**Depends on**: Nothing.
**Requirements**: REQ-42, REQ-43
**Success Criteria** (what must be TRUE):
  1. Backup (`agent/services/db_backup.py`) includes the Chroma vector dir so a restore keeps SQLite↔embeddings consistent; WAL is checkpointed and the DB VACUUMed on a schedule.
  2. Deleting a conversation/learning removes its vectors from Chroma (no orphans, no dangling references back through the `vector_store.py` rehydration path).
  3. Audit (`.governance/execution_log.json`) and execution logs redact PII/secret argument content before writing.
  4. A test simulates SQLite-written-but-embed-failed (and the reverse) and asserts the durability/erasure paths keep the two stores consistent.
**Plans**: TBD

### Phase 7: Config consolidation
**Goal**: One typed, documented source of truth for config — no inlined-default drift, no second silent loader.
**Depends on**: Nothing.
**Requirements**: REQ-50
**Success Criteria** (what must be TRUE):
  1. Every operator key is defined/typed/defaulted in one schema (`config_schema.py`), with no key read via an inlined default that diverges from the schema.
  2. The second loader (`services/config_cache.py` reading a separate `config.json`) is collapsed into the single `runtime_safety.load_config()` path or documented-and-removed; a call site can no longer ambiguously read two files. *(CONCERNS: two parallel config systems, 25 importers of `config_cache`)*
  3. A test/check asserts every runtime `cfg.get("…")` key is represented in the schema (schema drift is caught automatically, not by manual audit).
**Plans**: TBD

### Phase 8: Agent-loop decomposition
**Goal**: The core loop is a set of small, tested units instead of one 1,665-line function inside a 4,119-line file.
**Depends on**: Phase 3 (the characterization/test net) — do NOT refactor the critical path without it.
**Requirements**: REQ-51
**Success Criteria** (what must be TRUE):
  1. `_autonomous_run_impl_core` is decomposed into explicit decide/dispatch/verify/recover/emit units (extracting into the existing siblings `agent_loop_formatting.py` / `agent_safety.py` / `agent_hooks.py` where they already exist), each with its own tests.
  2. `services/` no longer imports `agent_loop` private internals; the hidden lazy back-reference import edges into the loop are removed or made explicit.
  3. The Phase 3 agent-loop tests stay green across the refactor (behavior preserved).
**Plans**: TBD

### Phase 9: Then build
**Goal**: Add the product capabilities the hardened core unlocks — a hardware-aware model browser, real `/v1` compatibility, frictionless install, and approval-gating as a visible feature.
**Depends on**: Phase 1 (security), Phase 3 (CI to gate the new contract tests).
**Requirements**: REQ-60, REQ-61, REQ-62, REQ-63
**Success Criteria** (what must be TRUE):
  1. A hardware-aware model browser in the UI lets the user discover models, see a recommended quant, download (resumable), and switch — built over the existing `hardware_detect` + `model_downloader`, with no manual GGUF copy + `runtime_config.json` edit. *(competitive-ecosystem: LM Studio quant picker + Ollama run-to-switch are "one service call away")*
  2. `/v1` honors `temperature` / `max_tokens`(→`n_predict`) / `stop` / `top_p` and **silently drops** unsupported params (never returns 400); a mapping fix in `openai_compat.py` plus contract tests in CI.
  3. Install ships prebuilt CPU/CUDA `llama-cpp-python` wheels (user never compiles the engine); the heavy ML stack (torch/chromadb) is opt-in, as the lite `dev` extra already proves works.
  4. Approval-gated mutation is a demoable, visible feature: file diffs and command previews are shown before an approved write/run executes.
**Plans**: TBD
**UI hint**: yes

### Phase 10: Frontend & docs cleanup
**Goal**: Remove front-end global coupling, define shared UI data once, and collapse documentation drift.
**Depends on**: Nothing.
**Requirements**: REQ-52
**Success Criteria** (what must be TRUE):
  1. Shared UI data (ASPECTS) is defined once and imported, not duplicated; the `window.*` global surface (`showToast`, `currentAspect`, `laylaChatFSM`, `LaylaUI`, …) is reduced behind a namespace/module boundary.
  2. Top-level docs are collapsed to a small canonical set (ARCHITECTURE + ROADMAP + CHANGELOG), with the rest archived — removing the overlapping start-path / doc drift flagged in the map.
  3. A check confirms no UI module depends on script load-order via an undeclared `window.*` global it does not own.
**Plans**: TBD
**UI hint**: yes

## Progress

| Phase | Plans Complete | Status | Completed |
|-------|----------------|--------|-----------|
| 1. Security finish | 0/0 | Not started | - |
| 2. Legal & launch safety | 0/0 | In progress (2 of 3 criteria done) | - |
| 3. Verifiable core (CI) | 0/0 | Not started | - |
| 4. Answer-quality eval harness | 0/0 | Not started | - |
| 5. Inference reliability | 0/0 | In progress (REQ-04 done) | - |
| 6. Data durability & privacy | 0/0 | Not started | - |
| 7. Config consolidation | 0/0 | Not started | - |
| 8. Agent-loop decomposition | 0/0 | Not started | - |
| 9. Then build | 0/0 | Not started | - |
| 10. Frontend & docs cleanup | 0/0 | Not started | - |

## Requirement Coverage

All 19 active requirements (REQ-10..REQ-63) map to exactly one phase. Validated requirements (REQ-01..REQ-04) shown against their delivering phase.

| Requirement | Phase | Status |
|-------------|-------|--------|
| REQ-01 | Phase 1 (basis) | Validated |
| REQ-02 | Phase 2 | Validated |
| REQ-03 | Phase 3 | Validated |
| REQ-04 | Phase 5 | Validated |
| REQ-10 | Phase 1 | Pending |
| REQ-11 | Phase 1 | Pending |
| REQ-12 | Phase 1 | Pending |
| REQ-20 | Phase 3 | Pending |
| REQ-21 | Phase 3 | Pending |
| REQ-22 | Phase 3 | Pending |
| REQ-30 | Phase 4 | Pending |
| REQ-31 | Phase 4 | Pending |
| REQ-40 | Phase 5 | Pending |
| REQ-41 | Phase 5 | Pending |
| REQ-42 | Phase 6 | Pending |
| REQ-43 | Phase 6 | Pending |
| REQ-50 | Phase 7 | Pending |
| REQ-51 | Phase 8 | Pending |
| REQ-52 | Phase 10 | Pending |
| REQ-60 | Phase 9 | Pending |
| REQ-61 | Phase 9 | Pending |
| REQ-62 | Phase 9 | Pending |
| REQ-63 | Phase 9 | Pending |

*Roadmap generated: 2026-06-29 — remediate-then-build, blast-radius ordered.*
