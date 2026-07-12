# Configuration Reference

Every operator-editable setting in `agent/runtime_config.json`, grouped by category. This file
is generated from `agent/config_schema.py` (`EDITABLE_SCHEMA`) — the single source of truth the
Settings UI and `GET /settings/schema` read. Edit settings in the Settings panel or in
`runtime_config.json`; some (model/context) require a restart.

## Core

| Key | Type | Default | Range | Description |
|-----|------|---------|-------|-------------|
| `ui_language` | string | `'en'` |  | Web UI language (en, es, de, fr, it, pt, ja, zh, ar, ru, ko). Falls back to English for missing strings. |
| `model_filename` | string | — |  | GGUF filename in models/ folder. Restart required. |
| `models_dir` | string | — |  | Path to models folder. Default: repo/models/ or ~/.layla/models/ |
| `sandbox_root` | string | — |  | Workspace root. Layla can only read/write within this path. |
| `temperature` | number | `0.2` | 0.01 … 1.5 | Lower = deterministic. Higher = creative. |
| `completion_max_tokens` | number | `256` | 64 … 8192 | Max tokens per response. Higher = longer, slower. |
| `ui_theme_preset` | string | `''` |  | Optional UI theme preset (applied on load). Leave blank for default. |
| `wizard_complete` | boolean | `False` |  | Web setup wizard completion flag (set by UI). |

## Model & sampling

| Key | Type | Default | Range | Description |
|-----|------|---------|-------|-------------|
| `n_ctx` | number | `4096` | 256 … 131072 | Context window size. Larger = more memory. |
| `n_gpu_layers` | number | `-1` | -1 … 99 | Layers on GPU. -1 = all. 0 = CPU only. |
| `n_batch` | number | `512` | 64 … 2048 | Batch size for prompt processing. |
| `n_threads` | number | — | 1 … 64 | CPU threads. null = auto. |
| `top_p` | number | `0.95` | 0 … 1 | Nucleus sampling. |
| `top_k` | number | `40` | 1 … 100 | Top-k sampling. |
| `repeat_penalty` | number | `1.1` | 1 … 2 | Penalize repetition. |

## Memory & retrieval

| Key | Type | Default | Range | Description |
|-----|------|---------|-------|-------------|
| `use_chroma` | boolean | `True` |  | Use ChromaDB for semantic search and learnings. |
| `embedder_prefer_quality` | boolean | `False` |  | Prefer heavier sentence-transformers embeddings over fast model2vec static embeddings (needs torch; better quality, slower on low-end). |
| `knowledge_chunks_k` | number | `5` | 1 … 20 | Chunks retrieved from knowledge base. |
| `learnings_n` | number | `30` | 5 … 100 | Learnings injected into context. |
| `semantic_k` | number | `5` | 1 … 20 | Semantic search results. |
| `memory_retrieval_min_adjusted_confidence` | number | `0.0` | 0.0 … 1.0 | Drop memory hits below this adjusted confidence in semantic recall (0 = no filter). |
| `project_discovery_auto_inject` | boolean | `False` |  | Sparse .layla/project_memory.json: inject deterministic workspace scan into context (filesystem only). |
| `people_codex_enabled` | boolean | `True` |  | Daily maintenance scans recent conversations for people you mention and saves them to the people codex. |
| `learning_quality_gate_enabled` | boolean | `True` |  | Reject low-quality distill content before DB insert (see distill.passes_learning_quality_gate). |
| `learning_quality_min_score` | number | `0.35` | 0.05 … 1.0 | Minimum heuristic score when learning_quality_gate_enabled is true. |
| `file_checkpoint_enabled` | boolean | `True` |  | Snapshot files before write_file / apply_patch / search_replace / write_files_batch for restore_file_checkpoint. |
| `file_checkpoint_max_count` | number | `200` | 0 … 50000 | Max checkpoint bundles per workspace; 0 = unlimited. Oldest deleted first. |
| `file_checkpoint_max_bytes` | number | `209715200` | 0 … 2147483647 | Max total bytes for checkpoints (~200MB default); 0 = unlimited. |
| `elasticsearch_enabled` | boolean | `False` |  | Mirror new learnings to Elasticsearch; use GET /memory/elasticsearch/search. |
| `elasticsearch_url` | string | `''` |  | Elasticsearch 8.x base URL, e.g. http://127.0.0.1:9200 |
| `elasticsearch_index_prefix` | string | `'layla'` |  | Index name prefix; learnings use {prefix}-learnings. |
| `elasticsearch_api_key` | string | — |  | Optional API key for Elasticsearch (cloud deployments). |

## Safety & guardrails

| Key | Type | Default | Range | Description |
|-----|------|---------|-------|-------------|
| `inline_initiative_enabled` | boolean | `False` |  | After 2+ tool steps, append one heuristic next-step line to the final reply. |
| `safe_mode` | boolean | `True` |  | Require approval for file writes and code execution. |
| `plugins_enabled` | boolean | `False` |  | Allow skill plugins to EXECUTE Python code (exec_module) and contribute MCP subprocess servers. Off = declarative skills only. Security-sensitive: only enable for plugins you trust. |
| `skill_venv_enabled` | boolean | `False` |  | On skill-pack install, provision a per-pack venv and pip-install its declared dependencies (heavier install; rolled back atomically on failure). |
| `skill_deps_require_pinned` | boolean | `True` |  | Reject skill-pack installs whose dependencies aren't version-pinned (name==x.y.z). Prevents supply-chain drift from floating deps. |
| `agent_hooks_enabled` | boolean | `True` |  | Allow operator-configured agent_hooks (session_start/pre_tool/post_tool) to run subprocess commands. session_start hooks run automatically when this is on. |
| `hooks_require_allow_run` | boolean | `True` |  | pre_tool/post_tool hooks run only when the turn has allow_run (or this is off). Keep on unless you trust every configured hook. |
| `uncensored` | boolean | `True` |  | Uncensored model behavior. |
| `nsfw_allowed` | boolean | `True` |  | Allow adult/NSFW content in system policy when combined with uncensored; use @lilith + register keywords per message for Lilith NSFW mode. |
| `enable_cot` | boolean | `True` |  | Chain-of-thought reasoning. |
| `deliberation_enabled` | boolean | `False` |  | Multi-aspect debate prompt: all six aspects weigh in before answering. Off by default — small models render the six scaffold lines as ~6 stitched answers. Leave off for normal single-voice chat. |
| `deliberation_mode` | string | `'auto'` |  | Multi-aspect deliberation: solo=one voice, auto=detect complexity, debate=2, council=3, tribunal=all 6. |
| `enable_self_reflection` | boolean | `False` |  | Post-response self-reflection. |
| `direct_feedback_enabled` | boolean | `False` |  | Opt-in blunt collaboration: honest critique of work (not personal attacks). Non-clinical — no psychiatric labels. See ETHICAL_AI_PRINCIPLES §11. |
| `pin_psychology_framework_excerpt` | boolean | `True` |  | Echo/Lilith: inject short non-clinical interaction-framework reminder (observation not diagnosis). |
| `custom_system_prefix` | string | — |  | Custom system addition (e.g. Always respond in bullet points). |
| `planning_strict_mode` | boolean | `False` |  | Mutating/run-class tools require an approved plan binding (plan_id) or allow_write/run on the request; see RUNBOOKS. |
| `engineering_pipeline_enabled` | boolean | `False` |  | Structured engineering partner: plan/execute modes with clarifier, critics, refiner, validator. See docs/STRUCTURED_ENGINEERING_PARTNER.md. |
| `completion_gate_enabled` | boolean | `False` |  | Deterministic quality gate: retry or structured failure when output does not meet minimum standards. |
| `deterministic_tool_routes_enabled` | boolean | `False` |  | Deterministic tool routing: reduce visible tools and constrain tool choice to task type. |
| `engineering_pipeline_default_mode` | string | `'chat'` |  | Default when POST /agent omits engineering_pipeline_mode. execute = full pipeline (slow). |
| `engineering_pipeline_max_clarify_rounds` | number | `3` | 1 … 10 | Reserved: max clarifier rounds per turn (protocol uses clarification_reply on follow-up requests). |
| `engineering_pipeline_validator_max_retries` | number | `1` | 0 … 2 | When execute-mode validator suggests retry, bounded re-runs of execute_plan. |
| `in_loop_plan_governance_enabled` | boolean | `True` |  | Long-goal in-loop planner uses execute_plan(step_governance=True) like /execute_plan. Set false for legacy behavior. |
| `in_loop_plan_default_max_retries` | number | `1` | 0 … 3 | Per-step governance retries for in-loop plans (same cap as /plans execute body). |
| `plan_governance_require_nonempty_step_tools` | boolean | `False` |  | Approve rejects mutating step types with empty tools[]; in-loop may auto-fill read-only defaults (marks _tools_auto_filled). |
| `plan_governance_reject_auto_filled_tools` | boolean | `False` |  | Governed steps fail if tools were auto-filled — forces explicit tools in the plan. |
| `plan_governance_strict_tool_evidence` | boolean | `False` |  | Edit/test steps need tool traces with substantive results (paths for writes; pytest/unittest evidence for tests). Disallows text-only proof. Implied when plan_governance_hard_mode is on. |
| `plan_governance_hard_mode` | boolean | `False` |  | One switch: same as nonempty tools on mutating steps + reject auto-filled tools + strict tool evidence. |
| `admin_mode` | boolean | `False` |  | Auto-approve dangerous tools (still audited). The hard shell command blocklist (rm/dd/format/…) always applies regardless. |
| `admin_auto_checkpoint` | boolean | `True` |  | When admin_mode, best-effort git commit before mutating file/shell tools. |
| `admin_blocklist_override` | boolean | `False` |  | Relaxes admin-mode APPROVAL gating for otherwise-blocklisted tools. NOTE: the hard shell command blocklist (rm/dd/format/…) still applies regardless — this does not grant those commands. Do not enable on shared machines. |
| `tool_approval_bypass` | boolean | `False` |  | DANGEROUS: auto-approve ALL tools with no prompt and no checkpoint (the easy 'yes to everything' switch). Off by default; disable when not needed. |

## Voice

| Key | Type | Default | Range | Description |
|-----|------|---------|-------|-------------|
| `tts_voice` | string | — |  | TTS voice (kokoro-onnx catalog). |
| `whisper_model` | string | — |  | STT model. tiny=fastest, medium=best. |
| `tts_speed` | number | `1.0` | 0.5 … 2 | TTS playback speed. |

## Scheduler

| Key | Type | Default | Range | Description |
|-----|------|---------|-------|-------------|
| `scheduler_study_enabled` | boolean | `True` |  | Enable study plan scheduler. |
| `scheduler_interval_minutes` | number | `30` | 5 … 120 | Minutes between scheduler runs. |
| `scheduler_recent_activity_minutes` | number | `90` | 15 … 480 | Activity window for scheduler. |

## Limits

| Key | Type | Default | Range | Description |
|-----|------|---------|-------|-------------|
| `performance_mode` | string | `'auto'` |  | CPU/RAM caps: low tightens ctx and tool budgets. auto = hardware tier. |
| `auto_tune_enabled` | boolean | `True` |  | Hardware-adaptive optimization: auto-detect the machine tier and set inference + pipeline weight (context size, prompt budget, extra LLM calls, timeouts) for the best speed/quality on ANY hardware. Turn off for fully manual control. Lock individual keys via auto_tune_locked_keys. |
| `max_tool_calls` | number | `5` | 1 … 50 | Max tool calls per agent turn (non-research). |
| `max_runtime_seconds` | number | `900` | 5 … 3600 | Max wall time per agent turn (seconds). Align with ui_agent_stream_timeout_seconds so the server does not stop before the browser. |
| `tool_call_timeout_seconds` | number | `60` | 5 … 600 | Max seconds a single tool call may run before being killed. |
| `approval_ttl_seconds` | number | `3600` | 60 … 86400 | Seconds before a pending approval expires (default: 1 hour). |
| `models_max_keep` | number | `0` | 0 … 100 | Daily maintenance prunes downloaded GGUFs to the newest N (the active model is always kept). 0 = keep all. |
| `hyde_enabled` | boolean | `False` |  | Enable HyDE retrieval (generates a hypothetical answer before embedding — extra LLM call per query, improves recall quality). |
| `research_max_tool_calls` | number | `20` | 1 … 100 | Max tool calls when research_mode is on. |
| `research_max_runtime_seconds` | number | `1800` | 30 … 14400 | Max wall time for research-style runs (seconds). |
| `llm_serialize_per_workspace` | boolean | `False` |  | Per-workspace autonomous_run lock; local llama generation stays globally serialized. Enable for multi-repo parallelism. |

## Remote

| Key | Type | Default | Range | Description |
|-----|------|---------|-------|-------------|
| `remote_enabled` | boolean | `False` |  | Allow remote API access. |
| `remote_api_key` | string | `''` |  | Bearer token required for non-localhost clients when remote_enabled (store via UI or edit runtime_config.json). |
| `allow_legacy_remote_api_key` | boolean | `False` |  | Honor the DEPRECATED plaintext remote_api_key. Off by default — a stale key won't authenticate. Prefer tunnel_token_hash (rotate via /remote/token/rotate). |
| `remote_rate_limit_per_minute` | number | `100` |  | When remote_enabled, max requests per minute per non-localhost IP (0 = unlimited). |
| `llama_server_url` | string | — |  | External llama.cpp server URL. Overrides local model. |

## Integrations

| Key | Type | Default | Range | Description |
|-----|------|---------|-------|-------------|
| `mcp_client_enabled` | boolean | `False` |  | Enable MCP stdio client (services/mcp_client.py). When true, the mcp_tools_call tool can reach configured mcp_stdio_servers (requires allow_run + approvals like shell). |
| `discord_webhook_url` | string | — |  | Discord webhook URL for discord_send. Server Settings → Integrations → Webhooks. |
| `discord_bot_token` | string | — |  | Discord bot token for full bot (voice, TTS, music). Create at Discord Developer Portal. |
