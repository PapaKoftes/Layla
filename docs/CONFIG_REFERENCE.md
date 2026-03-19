# Config Reference — runtime_config.json

For advanced users. Edit `agent/runtime_config.json` directly, or use **Settings ⚙** in the UI for common options.

**Restart the server** after changing model-related keys (`model_filename`, `models_dir`, `n_ctx`, `n_gpu_layers`, `n_batch`).

---

## Core

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| `model_filename` | string | — | GGUF filename in `models_dir`. Required. |
| `models_dir` | string | `~/.layla/models` or `repo/models/` | Path to folder containing .gguf files. |
| `sandbox_root` | string | `~` | Workspace root. Layla can only read/write within this path. |
| `temperature` | number | 0.2 | Sampling temperature. Lower = deterministic, higher = creative. |
| `completion_max_tokens` | number | 256 | Max tokens per response. |

---

## Model / inference

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| `n_ctx` | number | 4096 | Context window size. Larger = more memory. |
| `n_gpu_layers` | number | -1 | Layers on GPU. -1 = all, 0 = CPU only. |
| `n_batch` | number | 512 | Batch size for prompt processing. |
| `n_threads` | number | null | CPU threads. null = auto. |
| `n_threads_batch` | number | null | Batch threads. null = auto. |
| `n_keep` | number | 512 | Tokens to keep in context when sliding. |
| `top_p` | number | 0.95 | Nucleus sampling. |
| `top_k` | number | 40 | Top-k sampling. |
| `repeat_penalty` | number | 1.1 | Penalize repetition. |
| `stop_sequences` | array | `["\nUser:", " User:"]` | Stop generation at these strings. |
| `use_mmap` | boolean | true | Memory-mapped model loading. |
| `use_mlock` | boolean | false | Lock model in RAM (reduces swap). |
| `flash_attn` | boolean | true | Flash attention when available. |

---

## Memory & retrieval

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| `use_chroma` | boolean | true | ChromaDB for semantic search and learnings. |
| `knowledge_chunks_k` | number | 5 | Chunks retrieved from knowledge base. |
| `learnings_n` | number | 30 | Learnings injected into context. |
| `semantic_k` | number | 5 | Semantic search results. |
| `knowledge_max_bytes` | number | 4000 | Max bytes per knowledge chunk. |
| `retrieval_use_mmr` | boolean | false | Use MMR for retrieval diversity. |
| `retrieval_cross_encoder_limit` | number | 10 | Cross-encoder rerank limit. |

---

## Safety & behavior

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| `safe_mode` | boolean | true | Require approval for file writes and code execution. |
| `uncensored` | boolean | true | Uncensored model behavior. |
| `max_tool_calls` | number | 5 | Max tool calls per agent turn. |
| `enable_cot` | boolean | true | Chain-of-thought reasoning. |
| `enable_self_reflection` | boolean | false | Post-response self-reflection. |

---

## Voice (TTS / STT)

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| `tts_voice` | string | af_heart | TTS voice. Options: af_heart, af_sky, am_adam, bf_emma, bm_george. |
| `whisper_model` | string | base | STT model. tiny, base, small, medium. |
| `tts_speed` | number | 1.0 | TTS playback speed. |
| `whisper_device` | string | auto | Device for Whisper (auto, cpu, cuda). |

---

## Scheduler

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| `scheduler_study_enabled` | boolean | true | Enable study plan scheduler. |
| `scheduler_interval_minutes` | number | 30 | Minutes between scheduler runs. |
| `scheduler_recent_activity_minutes` | number | 90 | Activity window for scheduler. |

---

## Remote / external

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| `remote_enabled` | boolean | false | Allow remote API access. |
| `llama_server_url` | string | null | External llama.cpp server. Overrides local model. |
| `inference_backend` | string | auto | auto, local, remote. |

---

## Integrations (Discord, Slack)

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| `discord_webhook_url` | string | null | Discord webhook for `discord_send`. Server Settings → Integrations → Webhooks → New. |
| `discord_bot_token` | string | null | Full Discord bot (voice, TTS, music). Create at Discord Developer Portal. See discord_bot/README.md. |
| `slack_webhook_url` | string | null | Slack incoming webhook for notifications. |

**Discord setup:** 1) Server Settings → Integrations → Webhooks. 2) New Webhook, pick channel. 3) Copy Webhook URL. 4) Set `discord_webhook_url` in config or `DISCORD_WEBHOOK_URL` env.

---

## File location

- **Config file:** `agent/runtime_config.json` (gitignored)
- **Example:** `agent/runtime_config.example.json`
- **API:** `GET /settings`, `POST /settings`, `GET /settings/schema`
- **Export:** `GET /system_export` (full system state as JSON)
