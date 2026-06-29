# Requirements: Layla — Remediate, then Build

Derived from `.planning/PROJECT.md`, the adversarial audit (`.planning/codebase/CONCERNS.md`), and `.planning/research/SUMMARY.md`. IDs are stable; phases map to these.

## Validated (delivered, evidence on `master`)

- **REQ-01** — Remote callers cannot reach unauthenticated RCE or rewrite security config (proxy-aware trust boundary; `/v1`+`/agent` body-flag fail-closed; shell+mcp deny-by-default). *(tests: trust_boundary, ip_allowlist, shell_approval_gate)*
- **REQ-02** — No copyleft (AGPL) dependency bundled under the proprietary license; production launch defaults `--reload` off.
- **REQ-03** — Agent-loop core logic (decision/tool-call parsing + completion gate) is unit-tested without a model.
- **REQ-04** — Multi-model routing cannot OOM the process (bounded resident-model cache).

## Active (this milestone)

### Security finish (Phase 1)
- **REQ-10** — Forwarded-IP derivation follows **rightmost-trusted-hop** against a configurable trusted-proxy list (not leftmost XFF, not "socket loopback"). *(research: security-patterns)*
- **REQ-11** — When exposed (`remote_enabled`), the auth token is required even for loopback by default (`remote_require_auth_always` default-on-when-exposed).
- **REQ-12** — Provider secrets are stored via the OS keyring (DPAPI/Keychain/Secret Service) with plaintext fallback; not plaintext in `runtime_config.json`.

### Verifiable core (Phase 3) — *unblocked by research*
- **REQ-20** — CI runs **real** tiny-model inference end-to-end every PR (an `inference-smoke` job using a committed ~1 MB `stories260K` GGUF + a CPU-baseline llama build/wheel), asserting structural output properties.
- **REQ-21** — The agent-loop tests are no longer `collect_ignore`d on CI (run with `run_completion` mocked at the boundary, audited file-by-file).
- **REQ-22** — `release.yml` is gated on the test job; `run_completion` threads `seed`/`top_k` for deterministic assertions.

### Answer quality (Phase 4)
- **REQ-30** — Inline RAG grounding check (MiniCheck / NLI, CPU, no cloud judge) emits a `grounding` block and supports cite-or-abstain; gates hard only on threshold breach for retrieval answers.
- **REQ-31** — A 20–50 prompt golden-set regression suite (promptfoo, local model) runs on PR + nightly with per-test thresholds.

### Reliability & data (Phases 5–6)
- **REQ-40** — The unused async `LLMRequestQueue` is removed (or made the single live path); the inference concurrency model is documented honestly.
- **REQ-41** — `save_learning` does not hold the SQLite write transaction during embedding; `/health` reports model-load failure as unhealthy.
- **REQ-42** — Backup includes the Chroma vector dir (SQLite↔embeddings consistent on restore); WAL checkpointed + DB VACUUMed on schedule.
- **REQ-43** — Deleting a conversation/learning removes its vectors (no orphans); audit/exec logs redact PII/secret argument content.

### Maintainability (Phases 7–8, 10)
- **REQ-50** — One typed, documented config schema (no inlined-default drift; every operator key documented).
- **REQ-51** — `_autonomous_run_impl_core` decomposed into tested decide/dispatch/verify/recover/emit units; `services/` no longer imports `agent_loop` privates. *(depends on REQ-20/21 test net)*
- **REQ-52** — Shared UI data (ASPECTS) defined once; `window.*` global surface reduced; top-level docs collapsed.

### Then build (Phase 9)
- **REQ-60** — Hardware-aware model browser/downloader in the UI (discover/recommend-quant/download/switch) over the existing `hardware_detect` + `model_downloader`.
- **REQ-61** — `/v1` honors `temperature`/`max_tokens`(→`n_predict`)/`stop`/`top_p`, silently dropping unsupported params (never 400); contract tests added.
- **REQ-62** — Install ships prebuilt CPU/CUDA llama wheels; the heavy ML stack (torch/chromadb) is opt-in.
- **REQ-63** — Approval-gated mutation is a visible, demoable feature (diff/command previews).

## Milestone 2 — Friend-Ready (product North Star)

### Track A — Daily-Driver (programming-grade, benchmarked)
- **REQ-70** — A real coding model runs locally end-to-end on a 16GB CPU box; performance and quality are *measured*, not asserted (baseline: Qwen2.5-Coder-7B-Q4 ≈ 5 tok/s; good edits, weak from-scratch self-verify; spec-decoding measured unhelpful on CPU). *(done)*
- **REQ-71** — `recommend_kit(hardware, domain, prefer)` recommends the best **usable** model for the detected hardware + domain + priority (respecting a CPU usability ceiling), maps the domain to its affinity aspect, pairs a same-family draft only where it helps (GPU), and emits CPU/GPU-aware settings + a rationale. *(done; 9 tests)*
- **REQ-72** — The full stack (`chromadb`/`chroma-hnswlib`, `torch`) installs on a fresh CPU Windows box with **no C++ toolchain** (prebuilt wheels, or a `use_chroma:false` + lightweight vector fallback). *The transferability blocker.*
- **REQ-73** — First-run onboarding probes hardware, presents the recommended kit with a speed/quality choice, downloads it, and sets the default aspect (`recommend_kit` wired into `first_run`).
- **REQ-74** — A HumanEval/MBPP pass@1 benchmark harness runs the local model via `services.llm_gateway` and emits a scorecard (model, quant, tok/s, pass@1).
- **REQ-75** — Full-app E2E: a real coding task completes through the HTTP API (server + agent loop + tools), and a one-command install path provisions interpreter + venv + model on the target laptop.
- **REQ-76** — Each aspect carries a curated **kit** (skills/tools/system-prompt set) for its domain, not just a model.

### Track B — The Layla Interface (UI from scratch)
- **REQ-77** — `ui-next/` (Vite+React+TS) with a design-token system from the canonical palette (`--bg #0a0008`, `--accent #c0006a`, per-aspect colors, `--wf-cut` paneling, glyph/sigil SVG kit) in the **Warframe-mystic midpoint** aesthetic; FastAPI serves the static build.
- **REQ-78** — The core agent chat experience in the new aesthetic, wired to the existing API (streaming, tool calls, diff view, memory).
- **REQ-79** — A BG3-style **aspect creator**: name, sigil, trait sliders, voice, synthesized system-prompt, **and the kit** (model affinity + skills); persists to the existing aspect backend; the active aspect re-themes the shell.
- **REQ-80** — A Fallout-NV-style **intake quiz** (S.P.E.C.I.A.L.-style) that shapes the default aspect/personality; answers map to config + aspect weighting.
- **REQ-81** — Per-aspect motion/polish: transitions, glyph animation, optional sound cues; responsive.

## Out of Scope (this milestone)
- Horizontal scaling / multi-node inference (single-process model accepted).
- Platform-scale market ambition (personal-first; pivot to a layer-on-incumbent if it must scale — see PROJECT.md viability framing).
- Full rewrites; new niche features (German mode, etc.) until the core is hardened and focused.
- Out-of-process/container tool sandboxing beyond the existing path-jail + approvals (tracked as a later hardening tier).
