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

## Benchmark and auto-select

- `model_benchmark.run_benchmark()` stores tokens/sec in `~/.layla/benchmarks.json`
- `model_benchmark.select_fastest_model(available)` returns fastest from stored results
- Set `benchmark_on_load: true` to run on first model load

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
