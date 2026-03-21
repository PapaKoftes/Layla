# Potato mode (low-resource preset)

**Potato mode** is a single bundle of conservative settings for weak CPUs, little RAM, or when you want Layla to stay in the background. It does **not** replace choosing a small GGUF — pair it with a model sized for your hardware (see [MODELS.md](../MODELS.md)).

## What it does

Applied via **Web UI → Settings → Apply potato preset** or:

```http
POST /settings/preset
Content-Type: application/json

{"preset": "potato"}
```

The server merges only [schema-editable keys](../agent/config_schema.py) into `agent/runtime_config.json`. Typical merges include:

| Key | Effect |
|-----|--------|
| `performance_mode` | `low` — tighter caps via `system_optimizer.get_effective_config()` |
| `n_ctx`, `n_batch`, `n_gpu_layers` | Smaller context, smaller batch, CPU-only if layers set to `0` |
| `max_tool_calls`, `max_runtime_seconds` | Shorter agent turns |
| `research_max_*` | Shorter research-style runs |
| `use_chroma` | `false` — skips ChromaDB-heavy retrieval paths (BM25/FTS may still apply per code paths) |
| `completion_max_tokens`, `semantic_k`, `knowledge_chunks_k`, `learnings_n` | Less context per reply |
| `scheduler_study_enabled` | `false` — no periodic study scheduler |
| `whisper_model` | `tiny` — faster STT when you use voice |

Restart the FastAPI server after applying so the LLM and services reload config.

## Ethics and privacy

Potato mode is **local configuration only**. It does not change approval rules, logging to your SQLite DB, or the ethical framework in [ETHICAL_AI_PRINCIPLES.md](ETHICAL_AI_PRINCIPLES.md).

## Reverting

Use Settings to set values back, edit `runtime_config.json`, or remove keys and rely on defaults from `runtime_safety.load_config()`.
