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

## Out of Scope (this milestone)
- Horizontal scaling / multi-node inference (single-process model accepted).
- Full rewrites; new niche features (German mode, etc.) until the core is hardened and focused.
- Out-of-process/container tool sandboxing beyond the existing path-jail + approvals (tracked as a later hardening tier).
