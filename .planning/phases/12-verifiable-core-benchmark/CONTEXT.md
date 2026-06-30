# Phase 12 Context: Verifiable core & benchmark

**Status:** ▶ ACTIVE · **Requirements:** REQ-20, REQ-21, REQ-22, REQ-74 (merges remediation Phase 3 + Friend-Ready A5)

## Why this phase, now
Phase 11 proved the model runs and selects itself. But running it for real surfaced that **the test suite hangs on the live stack** — so we cannot currently claim "green on the real stack," and we have no *number* for coding quality. This phase makes the core **provably** correct and makes "good" **measurable**. It is the gate before building more on top.

## Goal
Green CI proves the real generation path AND the agent loop work (not mocked orchestration), and a benchmark turns coding quality into a tracked score.

## Success criteria (from ROADMAP)
1. Full suite runs green **on the real stack** — fix the `llm_gateway.run_completion` retry-sleep hang.
2. A blocking `inference-smoke` job drives `run_completion` end-to-end on a committed tiny model (`stories260K.gguf` or SmolLM2-360M); release gated.
3. A HumanEval/MBPP pass@1 harness emits a scorecard (model, quant, tok/s, pass@1) for the local model.

## Known facts / constraints
- `.venv-test` (3.12) mirrors the friend's tier; real inference works there.
- Research (`.planning/research/ci-llm-testing.md`) de-risked this: portable CPU wheel + `tiny_llm` fixture; commit a ~1MB model.
- The hang is in `services/llm_gateway.py::run_completion` at `time.sleep(backoff)` — a test that previously skipped (no llama-cpp) now attempts real completion and retry-loops. Fix = a proper seam/mock so unit tests never attempt a real backend, plus a *separate* opt-in smoke test that does.
- Keep pure-stdlib testability where possible; the smoke job is the one place that loads a real model.

## Approach (planned slices)
1. **Stop the hang**: find the test(s) that reach `run_completion` without a backend; inject a mock/seam (env flag or fixture) so unit runs never sleep-retry against a missing model. Verify the full suite completes.
2. **inference-smoke**: a marked test that loads SmolLM2-360M (already on disk) and asserts structural properties of `run_completion` output (dict shape, non-empty, token cap, stop honored). Wire into CI; gate release.
3. **Benchmark harness**: `scripts/benchmark_coding.py` runs a HumanEval/MBPP subset via the gateway, emits a JSON+markdown scorecard. First scorecard = Qwen2.5-Coder-7B baseline.

## Out of scope
- Full HumanEval (164) in CI — use a small representative subset for speed; full run is a local/nightly option.
- Cross-machine determinism guarantees (CPU kernels reorder float ops — assert structure, tolerate tiny logit noise).
