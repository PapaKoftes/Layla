# Layla

## What This Is

Layla is a **local-first, self-hosted AI agent platform** — a Python/FastAPI server that wraps a locally-loaded GGUF model (via `llama-cpp-python`) and exposes a tool-using agent loop over a web UI, CLI/TUI, an OpenAI-compatible `/v1` API, and optional MCP. It keeps all data on the operator's machine (SQLite + optional Chroma memory), expresses one "consciousness" through six personality *aspects*, and gates every side-effecting tool (file write / shell / code execution) behind explicit `allow_write`/`allow_run` + an approval flow. Primary user today: a single privacy-focused power engineer; aspirational: self-hosting operators who want a private, sovereign AI companion.

## Core Value

**A capable, tool-using AI that runs entirely on your own hardware and can safely act on your files/system — with no cloud, no telemetry, and human approval for anything destructive.** If everything else fails, that core loop (chat → model decides → approved tool runs → verified answer) must work and be trustworthy.

## Project Direction (this milestone)

**Remediate, then build.** An 88-finding adversarial audit (see `.planning/codebase/CONCERNS.md`) plus a fresh codebase map established that the product is capable but had a critical security class, an untested core, and architectural/data risk. This milestone first makes Layla **safe to expose, legal to ship, and verifiably correct**, then adds new capabilities (model browser, eval harness, product focus) on the hardened foundation.

## Requirements

### Validated (done, evidence on `master`)
- Remote trust-boundary class eliminated (proxy-aware auth; `/v1`+`/agent` body-flag fail-closed; shell+mcp deny-by-default; allowlist/rate-limit un-spoofable). Tests: `test_trust_boundary`, `test_ip_allowlist`, `test_shell_approval_gate`.
- AGPL dependency removed; production launch defaults `--reload` off.
- Agent-loop core logic (decision/tool-call parsing + completion gate) under test; model cache bounded (OOM SPOF closed).
- Hardened SSRF guard, sql read-only, archive/docker sandbox guards, secret redaction, port guard, first-run "no model" banner.

### Active (open — the ROADMAP phases)
- Make CI prove the core (real inference + agent loop run, releases gated).
- Answer-quality / grounding eval harness.
- Inference reliability (remove dead queue, embed-outside-txn, model-failure health) & data durability (joint backup, erasure, PII).
- Config consolidation (typed schema); agent-loop god-file decomposition.
- Then build: model browser, product focus / sprawl triage, frontend modularization.

### Out of Scope (for now)
- Horizontal scaling / multi-node inference (single-process model is accepted).
- Rewrites — prefer surgical, regression-safe changes.
- New niche features (German mode, etc.) until the core is hardened and focused.

## Key Decisions
- **Local-first, single process, one model + one global lock** — deliberate; no required cloud services.
- **Approval-gated mutation** is the product's real differentiator; keep deny-by-default.
- **Python 3.11/3.12 only** (dep stack caps <3.13); a lite `dev` extra + `setup_test_env.ps1` enable testing without the GPU/model build.
- **Verify against implementation, not docs** — every remediation is backed by a runnable test where possible.

## Evolution

- 2026-06: Adversarial audit (88 findings) → trust-boundary class remediation → independent re-review → class-elimination → core-logic tests + bounded model cache. GSD adopted; codebase map + this PROJECT.md established. Direction set to remediate-then-build.
