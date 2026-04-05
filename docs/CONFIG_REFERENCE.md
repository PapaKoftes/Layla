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
| `nsfw_allowed` | boolean | true | When true with `uncensored`, system head allows adult/NSFW policy lines. Web UI: left **Options → Content policy** or ⚙ Settings → Safety. |
| `max_tool_calls` | number | 2 | Max tool calls per agent turn (before effective-config / pressure tuning). |
| `max_runtime_seconds` | number | 30 | Max wall-clock time for a normal agent turn (research uses `research_max_runtime_seconds`). |
| `tool_call_timeout_seconds` | number | 60 | Max seconds a single tool call may run before being killed (5–600). |
| `approval_ttl_seconds` | number | 3600 | Seconds before a pending approval expires and returns 410 (60–86400). Default: 1 hour. |
| `chat_light_max_runtime_seconds` | number | 90 | Wall-clock cap for short non-tool chat (`_is_lightweight_chat_turn`); bounded by `max_runtime_seconds`, floor 30s. |
| `hyde_enabled` | boolean | false | Enable HyDE retrieval — generates a hypothetical answer before embedding for improved recall. Adds one extra LLM call per retrieval query. Disable on low-resource hardware. |
| `performance_mode` | string | auto | `low` / `mid` / `high` / `auto` — see `system_optimizer.get_effective_config()`. |
| `completion_cache_enabled` | boolean | true | Short-lived cache for identical non-stream completion prompts (key includes model + temperature + max_tokens). |
| `response_cache_enabled` | boolean | true | In-memory cache for repeated short chat turns (see `routers/agent.py`). |
| `tool_loop_detection_enabled` | boolean | true | Block runaway / ping-pong tool repetition (`services/tool_loop_detection.py`). |
| `anti_drift_prompt_enabled` | boolean | true | Inject global “minimize change / follow conventions” instructions into the system head. |
| `enable_cot` | boolean | true | Chain-of-thought reasoning. |
| `enable_self_reflection` | boolean | false | Post-response self-reflection. |
| `direct_feedback_enabled` | boolean | false | **Opt-in blunt collaboration:** system head encourages direct, specific critique of work (not personal attacks). Does **not** override non-clinical rules — no psychiatric labeling. See `docs/ETHICAL_AI_PRINCIPLES.md` §11. |
| `pin_psychology_framework_excerpt` | boolean | true | For **Echo** and **Lilith** aspects only, inject a short pinned reminder: collaboration-oriented psychology framing, observation-not-diagnosis, crisis handoff wording. |

---

## Geometry (optional kernels)

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| `geometry_frameworks_enabled` | object | ezdxf/cadquery/openscad/trimesh true | Per-kernel toggles for `layla.geometry` backends. |
| `openscad_executable` | string | openscad | OpenSCAD CLI for `openscad_render` op. |
| `geometry_subprocess_timeout_seconds` | number | 120 | Timeout for cadquery subprocess and OpenSCAD. |
| `geometry_external_bridge_url` | string | "" | Base URL for optional CAD program bridge (`cad_bridge_fetch` op). |
| `geometry_external_bridge_allow_insecure_localhost` | boolean | false | Allow localhost bridge URLs (dev only). |

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
