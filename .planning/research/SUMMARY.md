# Research Summary

**Date:** 2026-06-29 · **Inputs:** competitive-ecosystem, ci-llm-testing, eval-harness, security-patterns · **Confidence:** MEDIUM-HIGH (primary docs for technical claims; secondary for UX comparisons).

## Cross-cutting takeaways

1. **Most open blockers are smaller than they looked — concrete, cited solutions exist.**
   - *CI for real inference (C4/C5):* block the **instruction dispatch, not the library**; build with `-DGGML_NATIVE=OFF -DGGML_AVX512=OFF` or use the prebuilt **CPU wheel index** (py 3.10–3.12, matches Layla); test with **`stories260K`** (~1 MB, the model llama.cpp uses in its *own* CI, committable in-repo). Tiered gate: mocked (every PR) + tiny-real `inference-smoke` (every PR, seconds) + nightly. Determinism via `top_k=1`+`seed`+`n_threads=1` — requires threading `seed`/`top_k` through `run_completion → inference_router`.
   - *Eval (no cloud judge, small model):* **MiniCheck** (flan-t5-large, 770M, CPU) for inline RAG grounding/cite-or-abstain in a new `grounding_eval.py`; **promptfoo** for a 20–50 prompt golden set (local model as judge) on PR + nightly. DeepEval/Ragas/lm-eval-harness are the wrong shape for the inline gate.

2. **The product wins are mostly UX over existing infra, not new systems.**
   - *Model browser:* LM Studio's **hardware-aware quant picker** is "one service call away" — `hardware_detect.py` + the resumable `model_downloader.py` already exist; the gap is purely UI. Ollama's `run`-to-switch is the switching pattern.
   - *`/v1` compatibility:* honor `temperature/max_tokens/stop` — a **mapping fix in `openai_compat.py`** (`max_tokens → n_predict`), silently drop unsupported params (never 400). `create_chat_completion` already accepts them.
   - *Install:* never make the user compile the engine — ship **prebuilt CPU/CUDA wheels** and make torch/chromadb **opt-in** (the lite `dev` extra already proves the app runs without them).

3. **The moat is real and undersold.** Approval-gated mutation (file/shell/code) is exactly what OWASP LLM06 + the agent-security literature prescribe, and Open WebUI's equivalent is **still unbuilt** (stalled PR); Ollama/LM Studio don't attempt host-acting approvals. Position Layla as **"the local agent safe to let act on your machine,"** with diff/command previews as a feature.

4. **Security: the remediated class has residual edges + adjacent gaps.**
   - `real_client_ip` still takes the **leftmost XFF** on fall-through (spoofable); canonical is **rightmost-trusted-hop** (per uvicorn `ProxyHeadersMiddleware`) keyed on a **trusted-proxy list**, not "socket is loopback."
   - Make **`remote_require_auth_always` default-on when exposed** (the Ollama "~175k unauthenticated hosts" failure mode).
   - **Secrets** → OS keyring (`keyring`: DPAPI/Keychain/Secret Service) with plaintext fallback.
   - **Sandbox** is blocklist + in-process (Claude-Code tier); reference agents (OpenHands, Open Interpreter, smolagents) converge on **deny-by-default allowlist + out-of-process isolation** — Layla's stronger knobs exist but default off.

## Direct roadmap impacts
- **Phase 1 (security):** add rightmost-trusted-hop XFF + trusted-proxy config; `remote_require_auth_always` default-on-when-exposed; keyring secret storage. (New, research-surfaced.)
- **Phase 3 (CI):** now fully de-risked — concrete `inference-smoke` job + `tiny_llm` fixture + staged un-`collect_ignore`.
- **Phase 4 (eval):** MiniCheck + promptfoo; new `grounding_eval.py` + `grounding_eval_enabled` flag; observe-then-gate rollout.
- **Phase 9 (build):** hardware-aware model browser; `/v1` param mapping + conformance tests; prebuilt wheels + opt-in ML stack; make approval-gating a showcase feature.
