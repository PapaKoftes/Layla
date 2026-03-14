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
