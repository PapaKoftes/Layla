# Roadmap: Layla — Remediate, then Build

> **STRATEGIC REFRAME — 2026-06-30.** The remediation roadmap (Phases 1–10) is substantially
> **DONE** (R1–R8 + R10; **2508 tests green**; installer + self-test + pairing shipped). The product
> now re-tiers around the **wedge** in [`STRATEGY.md`](STRATEGY.md), executed via the
> [`UPGRADES.md`](UPGRADES.md) backlog. **Read those two first.** The Phase 1–10 detail below is
> retained as the (largely completed) remediation substrate.

## Tiers (the live plan — supersedes the phase ordering below)

### MVP — *"the local AI with a soul that runs on a potato, in your language"*  (narrow on purpose)
- ONE soulful aspect (companion + general assistant) on the surface; others opt-in kits.
- **Engine abstraction** (UPG-10) + **sqlite-vec** (UPG-02) + **FastEmbed/model2vec** (UPG-03) +
  **constrained decoding** (UPG-05) — less code, better low-end quality.
- Self-test-gated installer (UPG-30 ✅) + **Doctor panel** (UPG-31) + guided pairing (UPG-32 ✅) + **honesty card** (UPG-24).
- Clean **#1** UI, memory, knowledge ingest. **Scope cut** (UPG-00a) + retire trap installers (UPG-00c) + finish **R9** (UPG-00b).
- **CUT:** cluster mesh, tribunal council, gamification-as-headline, tool long-tail.

### V2 — *"credible assistant"*
- **Hybrid escalation** (UPG-01) — bigger-local / BYO-cloud; kills the quality objection.
- Project-aware coding context (UPG-21), **MCP plugins** (UPG-12), **Ollama backend** (UPG-06),
  FlashRank (UPG-04), DSPy (UPG-08), self-consistency (UPG-20).
- **Multilingual/Castilla flagship** (UPG-23), eval harness in CI (UPG-22), safe model download (UPG-35),
  Ollama + `/v1` interop (UPG-40/41).

### V3 — *"platform"*
- 2–3 opt-in aspect kits; **knowledge/memory sync** across paired instances (UPG-33);
  **VS Code + CLI + mobile PWA via tunnel** (UPG-34); **Tauri shell** (UPG-13); optional GPU path; accessibility (UPG-36).

### Dream — *"movement"*
- Sponsor-funded OSS personal-AI-OS; your instance follows you across devices via pairing; a
  community **MCP kit marketplace** (UPG-37). A cause, not a cap table (STRATEGY §verdict).

---

## Overview *(Milestone 1 — remediation; now substantially ✅, detail retained)*

Derived from `.planning/PROJECT.md`, `.planning/REQUIREMENTS.md`, the four research briefs in `.planning/research/`, and the clean-room codebase map (`.planning/codebase/`). Direction: **remediate, then build** — first make Layla *safe to expose, legal to ship, and verifiably correct*, then add new capability on the hardened foundation.

Phases are ordered by **blast-radius**: finish security (Phase 1) → legal/launch (Phase 2, mostly done) → make CI prove the core (Phase 3, now de-risked by research) → measure answer quality (Phase 4) → inference reliability (Phase 5) → data durability (Phase 6) → config consolidation (Phase 7) → agent-loop decomposition (Phase 8, depends on the Phase 3 test net) → then-build product work (Phase 9) → frontend/docs (Phase 10).

Coverage: every **active** requirement (REQ-10..REQ-63) maps to exactly one phase. Validated requirements (REQ-01..REQ-04) are shown against the phase that delivered them and marked `[x]`. `[x]` = done on `master`; `[~]` = partially done; `[ ]` = open.

## Phases

- [x] **Phase 1: Security finish** - Close the residual forwarded-header gap, default auth-always-when-exposed, move secrets to the OS keyring. ✅ DONE (4f05229, b1968ad, 77335b4)
- [x] **Phase 2: Legal & launch safety** - AGPL removed, reload-off, + dependency-license accounting & CI copyleft guard. ✅ DONE
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
  3. A `THIRD_PARTY`/`NOTICE` file documents dependency licenses, generated from a license scan; CI fails on a newly-introduced copyleft dependency. [x] *(`THIRD_PARTY.md` + `scripts/check_copyleft.py`, wired into `ci.yml`; 11 tests — commit on `master`)*
**Plans**: executed directly — see `phases/02-legal-launch/VERIFICATION.md`

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
  3. Audit (`.governance/execution_log.json`) and execution logs redact PII/secret argument content before writing. [x] *(`secret_filter.redact_payload` at the `log_execution` chokepoint; 11 tests — commit on `master`)*
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

---

## Milestone 2 — Friend-Ready (product North Star)

Layered on the remediation substrate (Phases 1–8). Goal: a friend on a **16GB CPU laptop** installs Layla and gets **very good, benchmarked, private programming help** through a **from-scratch UI**, where **each personality is a hardware-adaptive domain kit**. Decisions locked 2026-06-29 (see `MILESTONE-friend-ready.md`). The product work (old Phases 9–10) is subsumed here. Phases 11–15 = Track A (Daily-Driver); 16–19 = Track B (the Warframe-mystic UI).

- [~] **Phase 11: Local-coding foundation** — model+inference proven, hardware→kit recommender, compiler-free memory. *(A1 ✅, A2 ✅, A3 mostly ✅)*
- [ ] **Phase 12: Verifiable core & benchmark** — green suite on the real stack + a HumanEval/MBPP scorecard. *(merges remediation Phase 3 + A5)*
- [ ] **Phase 13: Onboarding & kit provisioning** — first-run provisions the optimal per-domain kit; kit contents + upgrades. *(A4, A7, A10)*
- [ ] **Phase 14: Coding-quality scaffolding** — repo-map, diff-edits, GBNF, codebase RAG, KV cache. *(A8 — the real quality lever)*
- [ ] **Phase 15: Full-app E2E, install & ecosystem seam** — E2E + one-command install; `/v1` backend seam + portable character cards. *(A6, A9)*
- [ ] **Phase 16: UI foundation** — `ui-next/` Vite+React(TS) + Warframe-mystic design tokens. *(B1)*
- [ ] **Phase 17: Core chat UI** — agent chat in the new aesthetic, wired to the API. *(B2)*
- [ ] **Phase 18: Personality creator & intake quiz** — BG3-style aspect creator + Fallout-NV quiz. *(B3, B4)*
- [ ] **Phase 19: UI polish & motion** — per-aspect transitions, glyphs, sound, responsive. *(B5)*

### Phase 11: Local-coding foundation  ✅ mostly done
**Goal**: Layla runs a real coding model and auto-selects the best one for the machine, on a compiler-less box.
**Requirements**: REQ-70, REQ-71, REQ-72
**Success Criteria**:
  1. A real coding model runs locally E2E; perf/quality **measured** not asserted. [x] *(Qwen2.5-Coder-7B; ~5 tok/s; spec-decoding measured unhelpful on CPU)*
  2. `recommend_kit(hw, domain, prefer)` picks the best **usable** model + maps to the affinity aspect. [x] *(9 tests)*
  3. Memory/RAG works with **no chromadb / no C++ toolchain**. [x] *(SQLite+NumPy fallback; 12+87 tests)*
  4. A one-command fresh-box install path provisions interpreter+venv+model. [ ] *(remaining A3 slice)*

### Phase 12: Verifiable core & benchmark
**Goal**: Green CI proves the real generation path AND the agent loop work; coding quality is a number.
**Requirements**: REQ-20, REQ-21, REQ-22, REQ-74
**Success Criteria**:
  1. The full suite runs green **on the real stack** (fix the `llm_gateway.run_completion` retry-sleep hang found 2026-06-29). [x] *(1734 passed, 0 failed on 3.12 `.venv-test`; conftest default-protects real-Llama tests; fixed a stale REQ-10/11 allowlist test — commit on `master`)*
  2. A blocking `inference-smoke` job drives `run_completion` end-to-end on a committed tiny model; release gated. [ ] *(seam ready: `LAYLA_TEST_REAL_LLM` opt-in; SmolLM2-360M on disk)*
  3. A HumanEval/MBPP pass@1 harness emits a scorecard (model, quant, tok/s, pass@1). [x] *(`scripts/benchmark_coding.py`, 8 tests; first scorecard **Qwen-Coder-7B 100% pass@1, 3.17 tok/s** — `benchmarks/`)*

### Phase 13: Onboarding & kit provisioning
**Goal**: First run detects hardware and provisions the optimal kit per domain; kits are complete, not just a model.
**Requirements**: REQ-73, REQ-76, REQ-85
**Success Criteria**:
  1. First-run probes hardware, offers the recommended kit (speed/quality choice), downloads it, sets the default aspect (wires `recommend_kit` into `first_run`). [ ]
  2. Each aspect carries curated skills/tools/system-prompt for its domain. [ ]
  3. Embedding-model selection per tier, IQ-quant options, benchmark-driven model choice. [ ]

### Phase 14: Coding-quality scaffolding
**Goal**: Make a CPU-class 7B produce results well above its size (the real lever, since the model is fixed).
**Requirements**: REQ-82
**Success Criteria**:
  1. Tree-sitter **repo-map** supplies relevant code within the small context window. [ ]
  2. **Search/replace diff-edit** output format (not whole-file rewrites). [ ]
  3. **GBNF grammar-constrained** tool/JSON output. [ ]
  4. **Codebase RAG** (using the Phase 11 fallback store) + **prompt/KV caching** of system-prompt + repo-map. [ ]

### Phase 15: Full-app E2E, install & ecosystem seam
**Goal**: A real coding task completes through the API; it installs in one command; existing tools can use Layla as a backend.
**Requirements**: REQ-75, REQ-83, REQ-84
**Success Criteria**:
  1. A real coding task completes end-to-end via the HTTP API (server + agent loop + tools). [ ]
  2. One-command install on a fresh CPU box. [ ]
  3. `/v1` hardened so Cline/Continue/Aider can point at Layla; aspects import/export as portable character cards. [ ]

### Phase 16: UI foundation
> **2026-06-30 correction:** the refactor already modularized `agent/ui/` (ES modules). EXPAND the existing modular UI to the Warframe-mystic aesthetic + full control surface — do NOT build a from-scratch `ui-next/` React app (that would rebuild existing code). See `WATERTIGHT-PLAN.md`.
**Goal**: A real `ui-next/` app exists with the locked aesthetic as code (not mockups).
**Requirements**: REQ-77
**Success Criteria**:
  1. `ui-next/` (Vite+React+TS) builds to static assets served by FastAPI. [ ]
  2. Design-token system from the canonical palette + `--wf-cut` paneling + glyph/sigil SVG kit; active aspect re-themes the shell. [ ]
**UI hint**: yes

### Phase 17: Core chat UI
**Goal**: The agent chat experience in the Warframe-mystic aesthetic, wired to the real API.
**Requirements**: REQ-78
**Success Criteria**:
  1. Streaming chat, tool-call rendering, diff view, and memory views work against the existing API. [ ]
**UI hint**: yes

### Phase 18: Personality creator & intake quiz
**Goal**: The personality-as-kit experience: create/edit aspects and a quiz that shapes the default.
**Requirements**: REQ-79, REQ-80
**Success Criteria**:
  1. BG3-style aspect creator (name, sigil, trait sliders, voice, synthesized prompt, **and the kit**), persisting to the aspect backend. [ ]
  2. Fallout-NV S.P.E.C.I.A.L.-style intake quiz maps answers to the default aspect + config. [ ]
**UI hint**: yes

### Phase 19: UI polish & motion
**Goal**: The finish — it feels like Layla.
**Requirements**: REQ-81
**Success Criteria**:
  1. Per-aspect transitions, glyph animation, optional sound cues; responsive. [ ]
**UI hint**: yes

## Progress

Milestone 1 (remediation substrate) and Milestone 2 (Friend-Ready product). Old Phases 9–10 are subsumed into Milestone 2. `[x]`=done, `[~]`=partial, `[ ]`=open.

| Phase | Status | Evidence |
|-------|--------|----------|
| **M1 — remediation** | | |
| 1. Security finish | ✅ Done | REQ-10/11/12; 58 tests (4f05229, b1968ad, 77335b4) |
| 2. Legal & launch | ✅ Done | REQ-02; copyleft guard + THIRD_PARTY; 11 tests (7d45082) |
| 3. Verifiable core (CI) | → merged into **Phase 12** | |
| 4. Answer-quality eval | Open | pairs with Phase 12 |
| 5. Inference reliability | ~ Partial | REQ-04 (model-cache bound) done |
| 6. Data durability & privacy | ~ Partial | REQ-43 log redaction done (4c68804); Chroma backup/erasure open |
| 7. Config consolidation | Open | |
| 8. Agent-loop decomposition | Open | |
| **M2 — Friend-Ready** | | |
| 11. Local-coding foundation | ~ Mostly done | REQ-70/71/72; inference + recommend_kit + memory fallback; 21+87 tests |
| 12. Verifiable core & benchmark | ~ In progress (2/3) | ✅ suite green (1734 pass) + ✅ benchmark (Qwen-7B 100% pass@1); next: inference-smoke CI wiring |
| 13. Onboarding & kit provisioning | Open | A4/A7/A10 |
| 14. Coding-quality scaffolding | Open | A8 — the real quality lever |
| 15. Full-app E2E, install & seam | Open | A6/A9 |
| 16. UI foundation | Open | B1 |
| 17. Core chat UI | Open | B2 |
| 18. Personality creator & quiz | Open | B3/B4 |
| 19. UI polish & motion | Open | B5 |

## Requirement Coverage

| Requirement | Phase | Status |
|-------------|-------|--------|
| REQ-01..04 | 1/2/12/5 | Validated |
| REQ-10, REQ-11, REQ-12 | Phase 1 | ✅ Done |
| REQ-20, REQ-21, REQ-22 | Phase 12 | Pending |
| REQ-30, REQ-31 | Phase 12 | Pending |
| REQ-40, REQ-41 | Phase 5 | Pending |
| REQ-42 | Phase 6 | Pending |
| REQ-43 | Phase 6 | ✅ Done (log redaction) |
| REQ-50 | Phase 7 | Pending |
| REQ-51 | Phase 8 | Pending |
| REQ-52 | Phase 16/17 | Pending |
| REQ-70 | Phase 11 | ✅ Done |
| REQ-71 | Phase 11 | ✅ Done |
| REQ-72 | Phase 11 | ✅ Done (memory fallback; install-path slice open) |
| REQ-73 | Phase 13 | Pending |
| REQ-74 | Phase 12 | Pending |
| REQ-75 | Phase 15 | Pending |
| REQ-76 | Phase 13 | Pending |
| REQ-77 | Phase 16 | Pending |
| REQ-78 | Phase 17 | Pending |
| REQ-79, REQ-80 | Phase 18 | Pending |
| REQ-81 | Phase 19 | Pending |
| REQ-82 | Phase 14 | Pending |
| REQ-83, REQ-84 | Phase 15 | Pending |
| REQ-85 | Phase 13 | Pending |
| REQ-60 (model browser) | Phase 13/16 | Pending |
| REQ-61 (/v1) | Phase 15 (→REQ-83) | Pending |
| REQ-62 (prebuilt wheels) | Phase 11/15 | ~ (llama+torch wheels working) |
| REQ-63 (approval demoable) | Phase 17 | Pending |

*Roadmap: 2026-06-29 — M1 remediate-then-build (blast-radius ordered) + M2 Friend-Ready (product).*
