# 12 -- Networking, Integrations & External Services

> Subsystem design document for the Layla AI agent.
> Covers: remote access, service discovery, observability, plugin/skill systems, device sync, and external service integrations.

---

## Table of Contents

1. [Tailscale Integration](#1-tailscale-integration)
2. [mDNS Discovery](#2-mdns-discovery)
3. [Cloudflare Tunnel](#3-cloudflare-tunnel)
4. [MCP Client](#4-mcp-client)
5. [Observability Stack](#5-observability-stack)
6. [Plugin & Skill System](#6-plugin--skill-system)
7. [Syncthing Multi-Device Sync](#7-syncthing-multi-device-sync)
8. [External Service Integrations](#8-external-service-integrations)
9. [Known Issues](#9-known-issues)
10. [Stability Assessment](#10-stability-assessment)

---

## 1. Tailscale Integration

**File:** `agent/services/tailscale_manager.py`

### Purpose

Alternative remote-access backend to Cloudflare Tunnel. Wraps the `tailscale` CLI to manage a mesh VPN connection, providing private-network access to Layla instances without exposing ports to the public internet.

### Architecture

The module is a thin CLI wrapper -- it shells out to the `tailscale` binary via `subprocess.run()` with a 15-second timeout on every call. There is no long-lived daemon management; each function call is a one-shot subprocess invocation.

### Public API

| Function | Description |
|---|---|
| `is_available()` | Checks if `tailscale` binary is on PATH via `shutil.which()`. |
| `get_status()` | Runs `tailscale status --json`, parses the JSON, returns a normalized dict with `running`, `ip`, `hostname`, `backend_state`, `tailnet`. |
| `start_tailscale(cfg)` | Runs `tailscale up`, optionally with `--authkey` for headless auth. |
| `stop_tailscale()` | Runs `tailscale down`. |
| `get_tailscale_ip()` | Runs `tailscale ip -4` to get the IPv4 address. |
| `get_connection_url(port)` | Returns `http://<tailscale_ip>:<port>` if Tailscale is running. |
| `funnel_start(port)` | Runs `tailscale funnel <port>` for public HTTPS exposure via Tailscale Funnel. |
| `funnel_stop(port)` | Runs `tailscale funnel --off <port>`. |

### Configuration

| Key | Type | Default | Description |
|---|---|---|---|
| `tailscale_enabled` | bool | `false` | Master enable flag. |
| `tailscale_auth_key` | str | `""` | Optional pre-auth key for headless `tailscale up`. |

### Completeness

Functionally complete for single-instance use. The module covers status, start, stop, IP retrieval, and Funnel (public HTTPS). It correctly handles the Tailscale JSON status schema including `CurrentTailnet`, `MagicDNSSuffix`, and `TailscaleIPs`.

**Missing:** No wiring to the main application startup sequence was observed -- the module exists as a callable library but is not auto-started. There is no periodic health check or reconnect loop. Funnel start uses a synchronous subprocess call that may time out since Funnel is a long-running process.

---

## 2. mDNS Discovery

**File:** `agent/services/mdns_discovery.py`
**Router:** `agent/routers/pairing.py`

### Purpose

Zero-configuration local-network discovery of Layla instances using Zeroconf (mDNS/DNS-SD). Broadcasts presence and discovers peers on the LAN, enabling multi-device pairing, inference offloading, and knowledge synchronization.

### Architecture

- **Service type:** `_layla._tcp.local.`
- **Library:** `zeroconf` (pure Python, optional dependency -- degrades gracefully if missing).
- **State:** Module-level globals protected by threading locks (`_lock` for the Zeroconf instance, `_peers_lock` for the peer dictionary).
- **Instance ID:** Persisted as a UUID in `.governance/instance_id`, stable across restarts.

### Advertised Metadata

| Property | Source |
|---|---|
| `device_name` | Config or `platform.node()` |
| `hardware_tier` | Auto-detected via PyTorch CUDA VRAM: `cpu`, `gpu_low` (<8 GB), `gpu_mid` (8-16 GB), `gpu_high` (>16 GB) |
| `models` | Comma-separated list from local GGUF path + Ollama API + `remote_model_name` |
| `api_port` | HTTP port from config (default 8000) |
| `version` | Read from `agent/VERSION` file |
| `instance_id` | Stable UUID |
| `platform` | `platform.system()` |

### Peer Discovery

The `_LaylaServiceListener` class handles Zeroconf callbacks (`add_service`, `update_service`, `remove_service`). Peers are stored in a dictionary keyed by `instance_id` with a `last_seen` timestamp. The `get_discovered_peers(max_age_s)` function filters stale peers (default 120-second window) and prunes them from the dictionary.

`get_best_peer_for_inference(min_tier)` ranks peers by hardware tier for offloading decisions.

### Pairing System (Router)

The `/pairing/` router provides a PIN-based pairing protocol:

1. **Initiate:** Device A calls `/pairing/pair` with the peer's `instance_id`. A 6-digit cryptographic PIN is generated with a configurable TTL (default 300 seconds).
2. **Confirm:** Device B calls `/pairing/confirm` with the PIN and instance ID. On match, the pairing is stored to `.governance/paired_devices.json` with a hashed shared secret.
3. **Permissions:** Each paired device has granular permissions: `read_learnings`, `write_learnings`, `inference_offload`, `sync_knowledge`, `remote_tools`. All default to conservative settings (reads yes, writes no, remote tools no).

### Completeness

The mDNS discovery and pairing system is the most thoroughly implemented networking feature. It includes:
- Service broadcast and browsing
- Peer health checking (HTTP /health probe)
- Hardware tier auto-detection
- Persistent paired-device storage with permissions
- Full REST API with 10 endpoints

**Missing:** The actual cross-device inference offloading and knowledge sync are not implemented -- the infrastructure (discovery, pairing, permissions) is in place but the data-plane protocols for forwarding inference requests or syncing learnings between paired peers are absent.

---

## 3. Cloudflare Tunnel

**Files:** `agent/services/tunnel_manager.py`, `agent/services/tunnel_auth.py`, `agent/services/remote_rate_limit.py`

### Purpose

Expose the local Layla API to the public internet via Cloudflare's `cloudflared` quick tunnel, with authentication, IP allowlisting, and rate limiting.

### Tunnel Manager (`tunnel_manager.py`)

Manages a `cloudflared tunnel --url <local_url>` subprocess. Key features:

- **Quick tunnel:** Fire-and-forget subprocess with a background thread that watches stderr for the assigned `trycloudflare.com` HTTPS URL.
- **Health checking:** HEAD-request probe against the tunnel URL with latency measurement.
- **Auto-restart:** After N consecutive probe failures (default 3), automatically stops and restarts the tunnel. This is Phase 5 functionality.
- **State:** Module-level `_proc`, `_last_url`, `_consecutive_failures` globals protected by a threading lock.

### Tunnel Auth (`tunnel_auth.py`)

A proper authentication module extracted from earlier inline middleware:

| Feature | Implementation |
|---|---|
| **Token generation** | `secrets.token_urlsafe(32)` -- 256-bit, URL-safe. |
| **Storage** | SHA-256 hash stored in `tunnel_token_hash`. Plaintext never persisted. |
| **Validation** | Constant-time comparison via `hmac.compare_digest`. |
| **Legacy fallback** | Still accepts `remote_api_key` (plaintext) for backward compatibility, with a deprecation warning logged. |
| **Token rotation** | `rotate_token()` generates new token + hash; caller persists. |
| **IP allowlist** | CIDR-aware; `tunnel_ip_allowlist` entries can be bare IPs or CIDRs. Localhost always allowed. |
| **Token expiry** | `tunnel_token_ttl_hours` + `tunnel_token_created_at` (ISO-8601). TTL of 0 = never expires. |
| **Combined gate** | `check_remote_access(token, ip, cfg)` runs IP check, then expiry, then token validation. |

### Rate Limiter (`remote_rate_limit.py`)

Sliding-window rate limiter for non-localhost clients:

- In-process memory using `collections.deque` per client key.
- 60-second sliding window.
- Stale buckets pruned every 60 checks (5-minute inactivity cutoff).
- Single-server only (no shared store for multi-worker).

### Completeness

The tunnel + auth + rate limiting stack is production-quality for single-server use. The auth module follows security best practices (constant-time comparison, hashed storage, CIDR allowlists, token rotation).

**Missing:** No integration with the pairing system -- tunnel auth and mDNS peer auth are completely separate systems. The rate limiter is in-process only, which breaks under multi-worker Uvicorn.

---

## 4. MCP Client

**File:** `agent/services/mcp_client.py`

### Purpose

Model Context Protocol (MCP) client for connecting to external tool servers via JSON-RPC over stdio. This gives Layla access to tools hosted in separate processes (filesystem, database, web scraping, etc.).

### Architecture

The client implements the MCP stdio transport protocol:

1. **Subprocess spawning:** Each MCP server is launched as a subprocess with `stdin`/`stdout`/`stderr` pipes.
2. **JSON-RPC over newline-delimited lines:** One JSON object per line, read/write via pipes.
3. **Handshake:** `initialize` request (protocol version `2024-11-05`) followed by `notifications/initialized`.
4. **Operations:** `tools/list`, `tools/call`, `resources/list`, `resources/read`.

### Server Configuration

Servers are defined in config under `mcp_stdio_servers` as a list of `{name, command, args}` objects. The `McpStdioServerSpec` dataclass validates each entry.

### Session Model

Each operation (list tools, call tool, etc.) spawns a fresh subprocess, performs the handshake, executes the request, and terminates the process. There is no persistent session or connection pooling. The `_readline_threaded` helper provides Windows-safe timeout on stdout reads.

### Tool Summary Injection

`get_cached_mcp_tool_summary_for_prompt(cfg)` builds a one-line-per-tool summary of all configured MCP servers, cached with a configurable TTL (`mcp_tool_summary_ttl_seconds`, default 300). This summary is injected into the LLM decision prompt so the agent knows which external tools are available.

### Configuration

| Key | Type | Description |
|---|---|---|
| `mcp_client_enabled` | bool | Master enable flag. |
| `mcp_stdio_servers` | list | Array of `{name, command, args}` server specs. |
| `mcp_tool_summary_ttl_seconds` | float | Cache TTL for tool summary (default 300). |

### Completeness

The MCP client is functionally complete for basic tool usage. It supports the core MCP operations and handles timeouts, errors, and Windows compatibility.

**Limitations:** No persistent sessions (each call re-spawns and re-handshakes), no SSE/HTTP transport (stdio only), no MCP prompt/sampling support. The per-call subprocess overhead could be significant for frequent tool use.

---

## 5. Observability Stack

**Files:** `agent/services/observability.py` (same as `telemetry.py`), `agent/services/telemetry.py`, `agent/services/otel_export.py`, `agent/services/langfuse_export.py`, `agent/services/elasticsearch_bridge.py`, `agent/services/health_snapshot.py`

### 5.1 Structured Event Logging (`observability.py`)

The core observability module. Emits structured events via standard `logging` or `loguru` (when available). Every event includes `timestamp`, `event_type`, `duration`, and `status`.

**Note:** `observability.py` and `telemetry.py` appear to be identical files (same content). The canonical import path is `services.observability` but some call sites use `services.telemetry`.

#### Events Tracked

| Event | Fields | Description |
|---|---|---|
| `agent_response` | aspect, duration_ms, status | Per-response timing |
| `run_budget_summary` | wall_time, tokens, tool_counts | Per-run resource usage |
| `tool_call` | tool, duration_ms, status | Individual tool execution |
| `tool_result` | tool, ok, duration_ms | Tool outcome (feeds reliability DB) |
| `learning_saved` | content_preview, source | Knowledge acquisition |
| `study_started/completed` | topic, duration_ms | Self-study lifecycle |
| `memory_retrieval` | query_preview, hits | Vector search |
| `retrieval_results` | query_preview, count, duration_ms | Retrieval with timing |
| `retrieval_cache_hit/miss` | query_preview, duration_ms | Cache performance |
| `agent_plan_created/step/completed` | steps, goal_preview | Planner lifecycle |
| `mission_created/started/step/completed/failed` | mission_id, goal_preview | Mission lifecycle (v1.1) |
| `execution_trace` | execution_id, pipeline_stage, tool_calls | Ops debug |
| `agent_decision` | duration_ms | LLM decision latency |
| `agent_started/shutdown` | duration_ms | Process lifecycle |
| `prompt_assembled` | total_tokens, sections, truncated | Prompt construction |

#### Performance Monitor Integration

Tool latency, retrieval latency, and agent decision latency are forwarded to `services.performance_monitor.record()` for the system optimizer to consume.

#### Tool Health Snapshot

`tool_health_snapshot()` aggregates tool reliability data from the database:
- **Slow tools:** Average latency above threshold (default 8000 ms).
- **Unreliable tools:** Success rate below 0.35 with sufficient samples (default 8).
- **Failure clusters:** Recent failure counts grouped by tool name (last 30 failures).

### 5.2 Local Telemetry (`telemetry.py`)

Local-only telemetry that writes to `layla.db` in the `telemetry_events` table. No network traffic -- purely local analytics.

| Function | Description |
|---|---|
| `log_event()` | Records task_type, reasoning_mode, model_used, latency_ms, success, performance_mode. |
| `log_model_outcome()` | Records per-model success/failure with score and latency. |
| `get_model_success_rates()` | Aggregates model success rates from local DB. |
| `get_user_profile()` | Analyzes recent events to determine simple_ratio vs. coding_ratio. |
| `suggest_optimization()` | Heuristic flags: `prefer_fast` (many slow runs), `prefer_coding_model` (frequent coding tasks). |

### 5.3 OpenTelemetry Export (`otel_export.py`)

Minimal OTel integration -- a `maybe_span()` context manager that creates a span when `opentelemetry_enabled` is true and the SDK is installed. No tracer provider configuration, no exporter setup. The span attributes are stringified key-value pairs.

**Configuration:** `opentelemetry_enabled` (bool).

### 5.4 Langfuse Export (`langfuse_export.py`)

Optional Langfuse span emission for run budget summaries.

**Configuration:** `langfuse_enabled`, `langfuse_public_key`, `langfuse_secret_key`, `langfuse_host` (default `https://cloud.langfuse.com`).

Emits a single span named `layla_run_budget` with the run summary as metadata. Falls back gracefully if the Langfuse SDK is not installed.

### 5.5 Elasticsearch Bridge (`elasticsearch_bridge.py`)

Optional Elasticsearch mirror for learnings, providing keyword search via ELK.

| Function | Description |
|---|---|
| `client_from_config()` | Creates an `Elasticsearch` client from config (URL + optional API key). |
| `index_learning()` | Indexes a learning document to `{prefix}-learnings` index. |
| `search_learnings()` | Multi-match query across `text` and `tags` fields. |

**Configuration:** `elasticsearch_enabled`, `elasticsearch_url`, `elasticsearch_api_key`, `elasticsearch_index_prefix` (default `"layla"`).

### 5.6 Health Snapshot (`health_snapshot.py`)

Provides sanitized config + dependency status for the `/health` endpoint.

- **Config whitelist:** 30+ safe keys exposed (no API keys, tokens, or credentials).
- **Dependency probes:** `llama_cpp`, `chroma` (with optional deep embed+search test), `faster_whisper`, `kokoro_onnx`/`pyttsx3`, `tree_sitter`, GPU detection.
- **Feature flags:** Derived from config (chroma, completion_cache, voice_input, etc.).
- **Effective config:** Merged runtime + effective caps, sanitized for public exposure.

---

## 6. Plugin & Skill System

**Files:** `agent/services/plugin_loader.py`, `agent/services/skill_packs.py`, `agent/services/skill_discovery.py`, `agent/services/skills.py` / `agent/services/markdown_skills.py`

### 6.1 Plugin Loader (`plugin_loader.py`)

Scans `plugins/*/plugin.yaml` for plugin manifests and registers three types of extensions:

| Extension Type | Registration Target | Mechanism |
|---|---|---|
| **Skills** | `layla.skills.registry.SKILLS` | YAML-defined skills with name, description, tools list, execution_steps. |
| **Tools** | `layla.tools.registry.TOOLS` | Python module (`tools.py`) in the plugin directory, calling `mod.register(TOOLS)`. |
| **Capabilities** | `capabilities.registry` | Structured `CapabilityImpl` registration with package, module_path, dependencies, config_keys. |

**Security:** Plugin YAML files are capped at 256 KB. Slug/name lengths are validated. The loader catches and collects errors per-plugin without aborting.

### 6.2 Skill Packs (`skill_packs.py`)

Installable skill packs from git repositories. Cloned to `.layla/skill_packs_installed/<slug>`.

| Function | Description |
|---|---|
| `list_installed()` | Lists installed packs by scanning the directory for `manifest.json`. |
| `install_from_git(url, name)` | Clones a git repo (depth 1), validates manifest, registers in skill_registry. |
| `remove_pack(pack_id)` | Removes the pack directory. |

**Security hardening (P1-7):**
- URL scheme allowlist: only `https://` and `git://`.
- Embedded credentials (`user:pass@host`) rejected.
- Slug validation: `[a-zA-Z0-9_-]+` only.
- Path confinement: resolved destination must be under `INSTALLED_DIR`.
- Manifest validation via `skill_manifest` module (when available).

### 6.3 Skill Discovery (`skill_discovery.py`)

A lightweight stub for suggesting skill packs when tasks fail. Records "skill gaps" (goal + tool + error) and provides heuristic pack suggestions based on keyword matching:

| Keywords | Suggested Pack |
|---|---|
| code, refactor, pytest, git | `engineering` |
| paper, arxiv, citation, research | `research` |
| translate, language, glossary | `translation` |
| dxf, gcode, cad, cam | `cad_cam` |

This is explicitly a stub -- the docstring says "extend with SQLite telemetry later."

### 6.4 Markdown Skills (`skills.py` / `markdown_skills.py`)

Loads markdown files as skills from multiple directories:

| Directory | Priority |
|---|---|
| `{workspace}/.layla/skills/` | First |
| `{workspace}/skills/` | Second |
| `{workspace}/.claude/skills/` | Third |
| `{workspace}/.cursor/skills/` | Fourth |

Each `.md` file can have YAML front matter with `name`, `triggers`, and `description`. The body is the skill content.

`pick_skills_for_goal()` scores skills against a goal string by matching triggers (weight 3) and description words (weight 1), returning the top 2 matches.

`skills_prompt_block()` formats matched skills into a prompt block for LLM injection, capped at `max_tokens` (default 800).

**Note:** `skills.py` and `markdown_skills.py` are identical files -- likely one is the canonical version and the other a copy.

---

## 7. Syncthing Multi-Device Sync

**Files:** `agent/services/syncthing_sync.py`, `agent/routers/sync.py`

### Purpose

Multi-device synchronization of Layla's data directory (learnings DB, knowledge base, Chroma index) via Syncthing's REST API. Designed as a file-level sync -- Syncthing manages the transport, Layla manages the REST API interaction.

### Architecture

The module communicates with a locally-running Syncthing daemon via its REST API (`http://127.0.0.1:8384` by default). Authentication uses the `X-API-Key` header. All HTTP calls use `urllib.request` with a 5-second timeout.

### Operations

| Function | Endpoint Hit | Description |
|---|---|---|
| `is_running()` | `GET /rest/system/ping` | Checks if Syncthing daemon is reachable. |
| `get_status()` | Multiple REST calls | Returns comprehensive status: folder state, completion %, per-device sync status. |
| `trigger_rescan()` | `POST /rest/db/scan` | Forces immediate folder rescan. |
| `get_device_id()` | `GET /rest/system/status` | Returns this device's Syncthing ID. |
| `add_device()` | `GET + PUT /rest/config` | Adds a peer device and shares the Layla folder with it. |

### Router Endpoints

| Method | Path | Description |
|---|---|---|
| `GET` | `/sync/status` | Full sync status with device list. |
| `POST` | `/sync/rescan` | Trigger rescan. |
| `GET` | `/sync/device-id` | This device's ID. |
| `POST` | `/sync/add-device` | Add peer and share folder. |
| `GET` | `/sync/setup-guide` | Step-by-step setup instructions. |

### Configuration

| Key | Type | Description |
|---|---|---|
| `syncthing_api_key` | str | Required to enable (never logged). |
| `syncthing_base_url` | str | Default `http://127.0.0.1:8384`. |
| `syncthing_folder_id` | str | Default `"layla-data"`. |

### Completeness

The Syncthing integration is well-implemented for its scope:
- Full CRUD for device management.
- Comprehensive status reporting with per-device completion percentages.
- Built-in setup guide endpoint.
- Graceful degradation when Syncthing is not running.

**Known limitation:** SQLite DB sync is file-level, meaning concurrent writes on two devices will produce `.sync-conflict` files. The setup guide explicitly warns about this.

---

## 8. External Service Integrations

### 8.1 Discord Bot

**Files:** `discord_bot/bot.py`, `discord_bot/config.py`, `discord_bot/state.py`, `discord_bot/music_resolver.py`, `discord_bot/rich_embeds.py`, `discord_bot/guild_config.py`, `discord_bot/error_handler.py`

**Status:** STABLE -- the most feature-complete external integration.

A full Discord bot (py-cord) with:

**Chat commands:**
- `/summon` / `/dismiss` -- Join/leave voice channel, bind to text channel.
- `/ask` -- Text question to Layla.
- `/note` -- Save a learning (operator-initiated only).
- `/chat_speak` -- Ask and speak the reply in voice.
- `/status`, `/ping` -- Bot and server status.

**Voice features:**
- `/tts` / `/say` -- Text-to-speech in voice channel.
- `/listen` / `/stop_listen` -- Record voice, transcribe via faster-whisper, reply, speak.
- Per-channel TTS on/off via `/config tts on|off`.

**Music features:**
- `/play` -- YouTube, Spotify, SoundCloud, Bandcamp, or search query.
- `/skip`, `/queue`, `/stop`, `/pause`, `/resume`.
- Multi-source resolution via `music_resolver.py`.
- Per-guild queue management.
- Per-channel music on/off via `/config music on|off`.

**Architecture:** Communicates with the Layla API server via `transports.base.call_layla_async()`. Rate-limited per channel (2-second debounce). Inbound security checks via `check_transport_inbound()`. Per-guild state management for voice clients, queues, and settings.

**Dependencies:** `py-cord[voice]`, `aiohttp`, `FFmpeg`, optional `yt-dlp`, `spotdl`, `kokoro-onnx`, `PyNaCl`.

### 8.2 Obsidian Vault Connector

**Files:** `agent/services/obsidian_sync.py`, `agent/routers/obsidian.py`

**Status:** STABLE -- bidirectional sync with conflict handling.

| Endpoint | Description |
|---|---|
| `POST /obsidian/connect` | Set vault path (persisted to config). |
| `GET /obsidian/status` | Connection status + diff summary. |
| `GET /obsidian/diff` | Dry-run: what would change on sync. |
| `POST /obsidian/sync` | Copy new/updated vault `.md` files to `knowledge/obsidian/`. Optional `force` to overwrite conflicts. |
| `GET /obsidian/suggest` | Suggest high-confidence learnings to export as Obsidian notes. |
| `POST /obsidian/export` | Write approved learnings to `vault/layla-exports/`. |

**Conflict resolution:** Newer mtime wins; vault wins on fresh import. Conflicts are skipped unless `force=true`. After sync, triggers Chroma re-indexing if enabled.

**Note format for exports:** YAML front matter with `source: layla`, `type`, `confidence`, `layla_id`, followed by the learning content.

### 8.3 Voice (STT/TTS)

**Files:** `agent/services/stt.py`, `agent/routers/voice.py`

**STT (`stt.py`):** faster-whisper based speech-to-text.
- Models: `base` (default), `small`, `medium`, `large-v3` -- configurable via `whisper_model`.
- Device: auto-detect (CUDA or CPU) via `whisper_device`.
- Features: VAD filtering, streaming transcription (progressive yields), voice mode detection (RMS energy threshold), prewarm (background model loading).
- Dependency recovery: if `faster_whisper` is not installed, attempts auto-install via `dependency_recovery.ensure_feature()`.

**TTS:** Not in the reviewed files, but referenced from the voice router as `services.tts.speak_to_bytes()`. The router maps aspect IDs to TTS speeds (e.g., Morrigan = 1.05x, Nyx = 0.82x, Eris = 1.20x). Primary engine is `kokoro-onnx` with `pyttsx3` fallback.

**Voice Router endpoints:**
- `POST /voice/transcribe` -- Audio bytes in, text out.
- `POST /voice/speak` -- Text in, WAV bytes out (with per-aspect speed).

### 8.4 OpenAI-Compatible API

**File:** `agent/routers/openai_compat.py`

**Status:** STABLE -- drop-in compatible with OpenAI client libraries.

Implements `/v1/models` and `/v1/chat/completions` following the OpenAI API format:

- **Models:** Returns `layla` plus one model per aspect (`layla-morrigan`, `layla-nyx`, etc.).
- **Chat completions:** Supports both streaming (SSE `text/event-stream`) and non-streaming modes.
- **Streaming:** Uses a background thread with a queue to bridge sync inference to async SSE.
- **Aspect routing:** Model name `layla-<aspect_id>` routes to the corresponding aspect.
- **Conversation persistence:** Messages are saved to the conversation DB after each completion.
- **Error handling:** Returns proper OpenAI-format error responses with `type`, `param`, `code`.

**Custom extensions:** `workspace_root`, `allow_write`, `allow_run`, `aspect_id`, `show_thinking`, `conversation_id` fields in the request body. Response includes `aspect` and `conversation_id` in addition to standard fields.

---

## 9. Known Issues

### 9.1 Duplicate Files

- `agent/services/skills.py` and `agent/services/markdown_skills.py` are identical files. One should be removed and the other treated as canonical. The coexistence risks divergence if one is edited and the other is not.
- `agent/services/observability.py` and `agent/services/telemetry.py` appear to contain the same content (structured event logging). Import paths may vary across call sites, creating confusion about which is the "real" module.

### 9.2 Unfinished Cross-Device Data Plane

The mDNS discovery and pairing system provides the control plane (find peers, pair, assign permissions), but the actual data plane is absent:
- No inference offloading protocol -- `get_best_peer_for_inference()` returns a peer dict but nothing consumes it to forward requests.
- No learning sync protocol between paired peers.
- No remote tool execution path despite the `remote_tools` permission flag.

### 9.3 Tailscale Funnel Subprocess Issue

`funnel_start()` calls `subprocess.run()` (blocking, with a 15-second timeout) on `tailscale funnel`, which is a long-running command. The timeout will fire before the funnel is established, and the function treats `TimeoutExpired` as a potential success. This is fragile -- the funnel process is not managed, and the module has no way to track its lifecycle after the timeout.

### 9.4 MCP Session-Per-Call Overhead

The MCP client spawns a new subprocess for every single operation (list tools, call tool, etc.). Each call incurs: process creation, MCP handshake (initialize + initialized notification), the actual request, and process teardown. For frequent tool use, this is significant overhead.

### 9.5 Rate Limiter Scope

`remote_rate_limit.py` uses in-process memory, which breaks under multi-worker Uvicorn deployments. Each worker maintains its own independent rate limit state.

### 9.6 Elasticsearch Bridge -- No Lifecycle

The ES bridge creates a new client on every `index_learning()` and `search_learnings()` call. There is no connection pooling, no index creation/mapping management, and no bulk indexing.

### 9.7 OpenTelemetry -- Bare Minimum

`otel_export.py` provides a single `maybe_span()` context manager but does not configure a tracer provider, exporter, or resource. If the OTel SDK is installed, it will create spans using the default no-op tracer unless the application's entrypoint separately configures the OTel pipeline. Effectively a placeholder.

### 9.8 Langfuse -- Single Span Type

Only emits a single span type (`layla_run_budget`). No traces, generations, or event tracking. The integration is minimal enough that it provides limited observability value.

### 9.9 Skill Discovery Is a Stub

`skill_discovery.py` logs skill gaps but does not persist them or act on them. `suggest_packs_for_goal()` is a hardcoded keyword matcher, not connected to any pack installation flow.

---

## 10. Stability Assessment

| Component | Rating | Justification |
|---|---|---|
| **Tailscale Manager** | **STABLE** | Clean CLI wrapper, correct JSON parsing, proper error handling. Funnel subprocess management is the only weak point. |
| **mDNS Discovery** | **STABLE** | Thread-safe, graceful degradation, comprehensive peer management. Production-ready for LAN discovery. |
| **Pairing System** | **STABLE** | Crypto-sound PIN generation, hashed secret storage, persistent paired-device state, granular permissions. |
| **Cloudflare Tunnel** | **STABLE** | Health checks, auto-restart, proper subprocess management. Proven pattern. |
| **Tunnel Auth** | **STABLE** | Constant-time comparison, SHA-256 hashing, CIDR-aware allowlists, token rotation, expiry. Security-first design. |
| **Remote Rate Limiter** | **FRAGILE** | Correct for single-worker but breaks silently under multi-worker. No external store option. |
| **MCP Client** | **STABLE** | Correct JSON-RPC implementation, Windows-safe I/O, timeout handling. Session-per-call is a design choice, not a bug. |
| **Observability (structured logging)** | **STABLE** | Comprehensive event coverage, dual-backend (stdlib + loguru), performance monitor integration. |
| **Local Telemetry** | **STABLE** | Privacy-safe, local-only, gated by config flag, correct DB integration. |
| **OpenTelemetry Export** | **INCOMPLETE** | Context manager exists but no tracer/exporter configuration. Needs application-level OTel setup to function. |
| **Langfuse Export** | **INCOMPLETE** | Single span type, no trace context, no generation tracking. Minimal value as-is. |
| **Elasticsearch Bridge** | **FRAGILE** | No connection pooling, no index management, no bulk operations. Works but inefficient. |
| **Health Snapshot** | **STABLE** | Clean config whitelisting, comprehensive dependency probing, safe for public exposure. |
| **Plugin Loader** | **STABLE** | Robust YAML parsing, three extension types, per-plugin error isolation, size limits. |
| **Skill Packs** | **STABLE** | URL sanitization, path confinement, manifest validation, slug checks. Security-hardened. |
| **Skill Discovery** | **INCOMPLETE** | Explicitly a stub. No persistence, no real analysis, hardcoded keyword matching. |
| **Markdown Skills** | **STABLE** | Clean front-matter parsing, multi-directory scanning, trigger-based matching. |
| **Syncthing Sync** | **STABLE** | Full REST API coverage, per-device completion tracking, graceful degradation, setup guide. |
| **Discord Bot** | **STABLE** | Feature-complete: chat, voice (STT/TTS), music (multi-source), per-guild state, rate limiting, security checks. |
| **Obsidian Sync** | **STABLE** | Bidirectional sync, conflict detection, Chroma re-indexing, export-to-vault flow. |
| **Voice (STT)** | **STABLE** | Multiple model sizes, auto device detection, VAD, streaming, dependency recovery. |
| **Voice (TTS)** | **STABLE** | Per-aspect speed mapping, dual-engine fallback (kokoro-onnx + pyttsx3). |
| **OpenAI-Compat API** | **STABLE** | Correct SSE streaming, aspect routing, conversation persistence, proper error format. |
| **Worker OS Limits** | **STABLE** | Cross-platform (POSIX rlimits + Windows Job Objects), CPU + memory caps, correct ctypes usage. |
| **Duplicate files (skills.py/markdown_skills.py, observability.py/telemetry.py)** | **FRAGILE** | Risk of silent divergence. Should be deduplicated. |

### Summary Counts

| Rating | Count |
|---|---|
| STABLE | 19 |
| FRAGILE | 3 |
| INCOMPLETE | 3 |
| DEAD | 0 |

---

## Appendix: Configuration Key Reference

| Key | Module | Type | Default |
|---|---|---|---|
| `tailscale_enabled` | tailscale_manager | bool | `false` |
| `tailscale_auth_key` | tailscale_manager | str | `""` |
| `mdns_enabled` | mdns_discovery | bool | `true` |
| `mdns_device_name` | mdns_discovery | str | hostname |
| `hardware_tier` | mdns_discovery | str | auto-detected |
| `pairing_pin_ttl` | pairing router | int | `300` |
| `cloudflared_path` | tunnel_manager | str | auto-detected |
| `remote_api_key` | tunnel_auth | str | `""` (deprecated) |
| `tunnel_token_hash` | tunnel_auth | str | `""` |
| `tunnel_token_created_at` | tunnel_auth | str | ISO-8601 |
| `tunnel_token_ttl_hours` | tunnel_auth | int | `0` (never) |
| `tunnel_ip_allowlist` | tunnel_auth | list | `[]` (all allowed) |
| `mcp_client_enabled` | mcp_client | bool | `false` |
| `mcp_stdio_servers` | mcp_client | list | `[]` |
| `mcp_tool_summary_ttl_seconds` | mcp_client | float | `300` |
| `opentelemetry_enabled` | otel_export | bool | `false` |
| `langfuse_enabled` | langfuse_export | bool | `false` |
| `langfuse_public_key` | langfuse_export | str | `""` |
| `langfuse_secret_key` | langfuse_export | str | `""` |
| `langfuse_host` | langfuse_export | str | `https://cloud.langfuse.com` |
| `elasticsearch_enabled` | elasticsearch_bridge | bool | `false` |
| `elasticsearch_url` | elasticsearch_bridge | str | `""` |
| `elasticsearch_api_key` | elasticsearch_bridge | str | `""` |
| `elasticsearch_index_prefix` | elasticsearch_bridge | str | `"layla"` |
| `telemetry_enabled` | telemetry | bool | `true` |
| `model_outcome_tracking_enabled` | telemetry | bool | `true` |
| `syncthing_api_key` | syncthing_sync | str | `""` |
| `syncthing_base_url` | syncthing_sync | str | `http://127.0.0.1:8384` |
| `syncthing_folder_id` | syncthing_sync | str | `"layla-data"` |
| `obsidian_vault_path` | obsidian_sync | str | `""` |
| `whisper_model` | stt | str | `"base"` |
| `whisper_device` | stt | str | `"auto"` |
| `voice_input_enabled` | health_snapshot | bool | `false` |
| `voice_output_enabled` | health_snapshot | bool | `false` |
| `discord_bot_token` | discord config | str | `""` |
