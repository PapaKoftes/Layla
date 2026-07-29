# Models

> Full guide: [../MODELS.md](../MODELS.md) in repo root.

Layla runs GGUF models via llama.cpp. Put `.gguf` files in `models/`. Set `model_filename` in `agent/runtime_config.json`.

---

## Model router (task-based)

When `coding_model`, `reasoning_model`, or `chat_model` are set in config, `model_router` selects by task type:

| Task type | Config key |
|-----------|------------|
| coding | `coding_model` |
| reasoning | `reasoning_model` |
| chat | `chat_model` |

---

## How Layla picks a model — and how benchmarks factor in

Layla deliberately does **not** ship a table of pre-baked coding scores for all 42 models: a quality
number you have not measured on your own box is marketing, not data. Selection works in two honest
layers instead.

**1. Hardware-fit first (always).** At first run / setup, `install/model_selector.py` filters the
catalog to what your RAM / VRAM can actually run, then picks by **category** (companion vs. coding vs.
reasoning …) and **size** — the largest model that still stays responsive on your hardware. On
CPU-only that ceiling is ~9B, because a 14B drops below ~2 tok/s and interactive use suffers.

**2. Measured-benchmark refinement (after you measure).** Once some models have actually been measured
on this machine, `recommend_model()` prefers the best-**measured** one among those that fit — ranking
by stored **coding pass@1 when present, then measured speed**. With no stored benchmarks this layer is
a no-op and hardware-fit stands. (This ranking read the wrong store key until it was fixed — see
`test_benchmark_driven_selection.py::test_benchmark_uses_real_producer_key`.)

So the only benchmark numbers Layla trusts *for selection* are the ones measured on *your* box:

- **Speed (tok/s + first-token latency + memory)** — set `benchmark_on_load: true` in
  `runtime_config.json` and Layla measures each model the first time it loads
  (`services/llm/model_benchmark.run_benchmark`), writing `~/.layla/benchmarks.json`. The one-command
  installer also measures the model it provisions. View stored results at `GET /platform/models`.
- **Coding pass@1** — run the HumanEval-style harness on any installed model:

  ```bash
  python scripts/benchmark_coding.py --model models/<your-model>.gguf
  ```

  (`--self-test` scores a known-good solver with no model, to prove the harness itself.)

### Shipping-model coding benchmark

The default coder model is measured with that harness before release and recorded in the changelog:

| Model | Harness tier | Result |
|-------|--------------|--------|
| **Qwen2.5-Coder-3B (Q4)** | core (10 tasks)  | **pass@1 100% — 10/10** |
| **Qwen2.5-Coder-3B (Q4)** | hard (12 tasks)  | **pass@1 100% — 12/12** |

The general **companion** default is a Qwen2.5-3B *Instruct* build (better conversation); the
`qwen2.5-coder-*` entries are the "Best for coding" picks the selector surfaces separately. On a
CPU-only *potato* box expect tens of seconds per reply for a 3B — the quality is there, latency is the
tradeoff (see the [hardware tiers](#tier-benchmarks) for the speed range per class).

### Model catalog — the 42 shipped picks

Every entry is hardware-filtered at selection time; **RAM** is the minimum Layla requires before it
will offer the model. **Uncensored** reflects the catalog's low-restriction content policy (a
deliberate, on-by-default product choice).

### General — Strong all-round capability, low restrictions

| Model | Size | RAM | Uncensored | Notes |
|-------|------|-----|:----------:|-------|
| `qwen2.5-1.5b-instruct-Q4_K_M` | 1.5B | 3 GB | no | Qwen2.5 1.5B (~1GB). Multilingual; ideal as a small translation/intent helper. |
| `qwen2.5-3b-instruct-Q4_K_M` | 3B | 4 GB | no | Qwen2.5 3B (~2GB). Multilingual general chat; good Spanish for a small model. |
| `jinx-7b-v2-Q4_K_M` | 7B | 6 GB | yes | Jinx 7B. No restrictions. 6GB VRAM. Best for 8GB cards. |
| `jinx-7b-v2-Q5_K_M` | 7B | 8 GB | yes | Jinx 7B Q5. Higher quality, same base. |
| `dolphin-3.0-llama3.1-8b-Q4_K_M` | 8B | 8 GB | yes | Dolphin 3.0 Llama 3.1 8B. Latest Dolphin series. No restrictions. |
| `dolphin-2.9.4-llama3.1-8b-Q4_K_M` | 8B | 8 GB | yes | Dolphin 2.9.4 Llama 3.1 8B. Uncensored, strong function calling. |
| `hermes-3-llama-3.1-8b-Q4_K_M` | 8B | 8 GB | yes | Hermes 3 Llama 3.1 8B. Minimal refusals. Strong instruction following. |
| `wizardlm-2-7b-Q4_K_M` | 7B | 8 GB | yes | WizardLM 2 7B. Instruction-tuned, capable. Low restrictions. 8GB VRAM. |
| `hermes-3-llama-3.1-8b-Q5_K_M` | 8B | 10 GB | yes | Hermes 3 Llama 3.1 8B Q5. Higher quality. |
| `dolphin-2.9.3-mistral-nemo-12b-Q4_K_M` | 12B | 12 GB | yes | Dolphin 2.9.3 Mistral Nemo 12B. Uncensored. 128K context window. |
| `mistral-nemo-12b-heretic-Q4_K_S` | 12B | 12 GB | yes | Mistral Nemo 12B Heretic. Uncensored. 128K context. |
| `solar-10.7b-instruct-v1-Q4_K_M` | 10.7B | 12 GB | yes | Solar 10.7B. Strong 10B class model. Very capable for size. 12GB VRAM. |
| `qwen2.5-14b-instruct-Q4_K_M` | 14B | 14 GB | no | Qwen 2.5 14B. Strong general model. Chinese + English bilingual. Low refusals. |
| `jinx-20b-Q2_K` | 20B | 16 GB | yes | Jinx 20B Q2. Fits 8GB VRAM. Quality tradeoff. |
| `mistral-small-24b-instruct-Q4_K_M` | 24B | 20 GB | yes | Mistral Small 24B. Open weights, low restrictions. 16GB VRAM sweet spot. |
| `jinx-20b-Q4_K_M` | 20B | 24 GB | yes | Jinx 20B. No restrictions. Default pick. 12GB+ VRAM or 24GB RAM. |
| `jinx-20b-Q5_K_M` | 20B | 28 GB | yes | Jinx 20B Q5. Best quality tier for 14GB VRAM. |

### Coding — Code generation, debugging, refactor specialists

| Model | Size | RAM | Uncensored | Notes |
|-------|------|-----|:----------:|-------|
| `qwen2.5-coder-1.5b-instruct-Q4_K_M` | 1.5B | 3 GB | no | Qwen2.5 Coder 1.5B Q4 (~1.1GB). Minimal-disk floor for very constrained machines. |
| `qwen2.5-coder-3b-instruct-Q4_K_M` | 3B | 4 GB | no | Qwen2.5 Coder 3B Q4 (~2GB). Multilingual incl. Spanish. Fast on older CPUs; light on disk. |
| `qwen2.5-coder-7b-instruct-Q4_K_M` | 7B | 8 GB | no | Qwen 2.5 Coder 7B. Dedicated code specialist. 8GB VRAM. |
| `qwen2.5-coder-14b-instruct-Q4_K_M` | 14B | 14 GB | no | Qwen 2.5 Coder 14B. Top-tier code generation, refactor, review. |
| `deepseek-coder-v2-lite-instruct-Q4_K_M` | 16B | 16 GB | yes | DeepSeek Coder V2 Lite 16B (MoE). Elite code model, 236B params active 16B. 16GB VRAM. |
| `qwen2.5-coder-32b-instruct-Q4_K_M` | 32B | 28 GB | no | Qwen 2.5 Coder 32B. Best open coding model at 24GB VRAM. Rivals GPT-4 on code. |

### Reasoning — Math, logic, step-by-step problem solving (DeepSeek R1 family)

| Model | Size | RAM | Uncensored | Notes |
|-------|------|-----|:----------:|-------|
| `deepseek-r1-distill-qwen-7b-Q4_K_M` | 7B | 8 GB | yes | DeepSeek R1 Distill Qwen 7B. Reasoning/math/coding on mid-range hardware. |
| `deepseek-r1-distill-llama-8b-Q4_K_M` | 8B | 8 GB | yes | DeepSeek R1 Distill Llama 8B. Reasoning on Llama base. 8GB VRAM. |
| `deepseek-r1-distill-qwen-14b-Q4_K_M` | 14B | 14 GB | yes | DeepSeek R1 Distill Qwen 14B. Best reasoning below 16GB VRAM. Math, analysis, code. |
| `deepseek-r1-distill-qwen-32b-Q4_K_M` | 32B | 28 GB | yes | DeepSeek R1 Distill Qwen 32B. Elite reasoning. 24GB VRAM. |
| `deepseek-r1-distill-llama-70b-Q4_K_M` | 70B | 48 GB | yes | DeepSeek R1 Distill Llama 70B. Maximum reasoning quality. 40GB+ VRAM. |

### Creative — Roleplay, fiction, long-form writing, minimal guardrails

| Model | Size | RAM | Uncensored | Notes |
|-------|------|-----|:----------:|-------|
| `fimbulvetr-11b-v2-Q4_K_M` | 11B | 12 GB | yes | Fimbulvetr 11B. No restrictions. Roleplay, creative writing, narrative specialist. |
| `lumimaid-v0.2-12b-Q4_K_M` | 12B | 12 GB | yes | Lumimaid 12B. Uncensored creative/companion. Strong character work. |
| `midnight-rose-70b-Q4_K_M` | 70B | 48 GB | yes | Midnight Rose 70B. Uncensored flagship for creative, narrative, and roleplay. 40GB+ VRAM. |

### Fast — Under 8GB VRAM; daily driver for low-end or secondary tasks

| Model | Size | RAM | Uncensored | Notes |
|-------|------|-----|:----------:|-------|
| `qwen2.5-coder-0.5b-instruct-Q4_K_M` | 0.5B | 1 GB | no | Qwen2.5 Coder 0.5B — speculative-decoding draft for the 7B/14B coder (same tokenizer). |
| `smolLM2-360M-Q2_K` | 360M | 2 GB | no | SmolLM 360M Q2. Minimum viable model. 2GB RAM. |
| `smolLM2-360M-Q4_K_M` | 360M | 3 GB | no | SmolLM 360M Q4. 3GB RAM. Entry-level hardware. |
| `tinydolphin-1.1b-Q4_K_M` | 1.1B | 3 GB | yes | TinyDolphin 1.1B. Uncensored. 3GB RAM. Old/slow PCs. |
| `dolphin-2.6-mistral-7b-Q3_K_M` | 7B | 5 GB | yes | Dolphin 2.6 Mistral 7B Q3. 5GB VRAM. Smallest full uncensored. |
| `dolphin-2.6-mistral-7b-Q4_K_M` | 7B | 6 GB | yes | Dolphin 2.6 Mistral 7B. Fast, uncensored. 6GB VRAM. |

### Flagship — 40GB+ VRAM; maximum quality, no restrictions

| Model | Size | RAM | Uncensored | Notes |
|-------|------|-----|:----------:|-------|
| `dolphin-2.9-llama3-70b-Q2_K` | 70B | 32 GB | yes | Dolphin 2.9 Llama 3 70B Q2. 32GB system RAM. Quality tradeoff. |
| `dolphin-2.9-llama3-70b-Q4_K_M` | 70B | 40 GB | yes | Dolphin 2.9 Llama 3 70B. Flagship uncensored. 40GB+ VRAM. |
| `dolphin-3.0-llama3.3-70b-Q4_K_M` | 70B | 40 GB | yes | Dolphin 3.0 Llama 3.3 70B. Latest flagship. No restrictions. Best for 48GB VRAM. |
| `hermes-3-llama-3.1-70b-uncensored-Q4_K_M` | 70B | 40 GB | yes | Hermes 3 Llama 3.1 70B Uncensored. No restrictions. 40GB+ VRAM. |
| `qwen2.5-72b-instruct-Q4_K_M` | 72B | 48 GB | no | Qwen 2.5 72B. Flagship general model. Near GPT-4 class. 40GB+ VRAM. |

---

## Dynamic Hardware Optimization

Layla detects your hardware at startup and sets optimal inference parameters
automatically via `services/hardware_probe.py`.

### What it does

1. **Probes** RAM, CPU cores, GPU (CUDA/Metal), and model file size
2. **Classifies** your system into a tier: `potato / standard / performance / high_end`
3. **Recommends** `n_ctx`, `n_batch`, `n_threads`, `n_gpu_layers`, `flash_attn`, etc.
4. **Applies** recommendations as defaults -- your `runtime_config.json` values override them
5. **Injects** a capability summary into every system prompt so Layla knows what she can do

### Tier benchmarks

| Tier | RAM | GPU | Recommended n_ctx | Expected speed |
|------|-----|-----|-------------------|----------------|
| potato | <8 GB | None | 2048 | ~3-8 tok/s |
| standard | 8-16 GB | None | 4096 | ~8-20 tok/s |
| performance | 16-32 GB | >=4 GB VRAM | 4096 | ~20-60 tok/s |
| high_end | 32+ GB | >=8 GB VRAM | 8192 | ~60+ tok/s |

### No manual tuning needed

You only need to set `model_filename` in `runtime_config.json`.
Everything else is computed from your hardware.  You can still override any
setting explicitly -- hardware defaults never overwrite config-file values.

### Known constraints

- `speculative_decoding_enabled` is **always forced false** by the probe.
  There is a llama-cpp-python <=0.3.16 bug where `draft_model` forces
  `_logits_all=True` but the `scores` array stays sized `(n_batch, vocab)`,
  causing a broadcast crash on any prompt longer than `n_batch` tokens.
  The probe includes a post-load resize guard, but disabling speculative
  decoding is the safest default until the bug is fixed upstream.
- `flash_attn` is only enabled on GPU tiers (`performance`, `high_end`)
  to avoid issues on CPU-only builds.
