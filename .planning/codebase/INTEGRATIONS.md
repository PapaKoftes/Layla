---
last_mapped_commit: dc0b9c0ad8bdb1cba9afea771ad54a55473ec14d
---
# External Integrations

**Analysis Date:** 2026-06-29

Layla is local-first and sovereignty-oriented: nearly every external integration is **optional and off by default**, degrading to a no-op when its daemon/credential is absent. The only "required" external surface is an inference backend (a local GGUF by default — no network), and a vector/SQLite store on local disk. All outbound network fetches funnel through a hardened SSRF guard.

Legend: **[required]** = needed for basic operation · **[optional]** = feature gated by config/install, default off.

## Inference Backends

Routed by `agent/services/inference_router.py` via `inference_backend` (`auto | llama_cpp | openai_compatible | ollama`) and helpers in `agent/services/llm_gateway.py`.

- **Local GGUF via llama-cpp-python** **[required, default]** — no network. Selected when no `llama_server_url`/`ollama_base_url` is set. Model resolved from `models_dir` (`~/.layla/models`) / `model_filename`.
- **Ollama** **[optional]** — set `ollama_base_url` (or legacy `llama_server_url` on port 11434). Uses OpenAI-compatible `/v1/chat/completions`. Also used for embeddings (`agent/services/embedding_service.py` `_embed_batch_ollama`). See `OLLAMA.md`.
- **OpenAI-compatible HTTP** **[optional]** — vLLM / LiteLLM proxy / any OpenAI API. Selected when a non-Ollama URL is configured.
- **LiteLLM multi-provider gateway** **[optional, default off]** — `agent/services/litellm_gateway.py`, master switch `litellm_enabled`. 100+ providers with failover (`litellm_fallback_chain`), cost tracking, circuit breaker. Keys via `litellm_api_keys` (provider → key).
- **Cluster offload** **[optional]** — offload generation to a paired Layla device on the LAN (`cluster_offload_enabled`; fallback chain local GPU → local CPU → paired device → queue). See `agent/services/inference_router.py`.

## Outbound Network Tools (SSRF-guarded)

- **Hardened SSRF guard** — `agent/services/url_guard.py` is the single source of truth (`check_url` / `is_safe_url`). Enforces: http/https only (blocks `file://`, `ftp://`, `gopher://`); rejects embedded credentials; normalizes obfuscated IPv4 (decimal/hex/octal); resolves DNS and checks **every** resolved address (anti DNS-rebinding); blocks private/loopback/link-local/reserved/multicast/unspecified and IPv4-mapped IPv6. Pure stdlib. Tested in `agent/tests/test_url_guard.py`.
- **Web fetch / crawl tools** **[optional]** — `agent/layla/tools/impl/web.py` and `agent/services/web_crawler.py` call `is_safe_url` on every fetch. Optional `web_allowlist` further restricts hosts. Headless browsing via Playwright (extra `crawl`); `agent/services/browser.py`.
- **Research tools** **[optional]** (extra `research`) — DuckDuckGo search, Wikipedia, arXiv, PDF ingest.

## Remote Access & Pairing

All disabled by default; enabling requires `remote_enabled=true` plus an API key and explicit endpoint allowlisting.

- **Remote HTTP exposure** **[optional, default off]** — `remote_enabled`, `remote_api_key`, `remote_allow_endpoints`, `remote_mode` (`observe`), `remote_rate_limit_per_minute`, `remote_cors_origins`. Auth in `agent/services/auth.py`; loopback is trusted only for direct (non-tunnel) connections (`agent/main.py` ~line 756).
- **Cloudflared tunnel** **[optional]** — `agent/services/tunnel_manager.py`. Requires `cloudflared` on PATH or `cloudflared_path`. Health-checks + auto-restart. Started via `POST /remote/tunnel/start`.
- **Tailscale mesh VPN** **[optional]** — `agent/services/tailscale_manager.py` (alternative to cloudflared). `tailscale_enabled`, `tailscale_auth_key`, uses the `tailscale` CLI.
- **ngrok** — referenced as a recognized tunnel type in trust-boundary logic (`agent/main.py`, `agent/services/auth.py`), no dedicated manager; cloudflared/Tailscale are the shipped backends.
- **Tunnel auth / audit** — `agent/services/tunnel_auth.py`, `agent/services/tunnel_audit.py`, IP allowlist (`tunnel_ip_allowlist`). Tests: `agent/tests/test_tunnel_*.py`, `test_ip_allowlist.py`, `test_trust_boundary.py`.
- **mDNS / device pairing** **[optional]** (extra `network`, zeroconf) — `agent/services/mdns_discovery.py` broadcasts `_layla._tcp.local.` with device/hardware/model metadata. Pairing flow via `agent/routers/pairing.py` + `agent/ui/js/layla-pairing.js`. `mdns_enabled` (default true when installed). Tests: `test_mdns_discovery.py`, `test_pairing.py`.

## Chat Transports (inbound)

Thin adapters over a unified `call_layla()` in `transports/base.py`. Inbound security is OpenClaw-style: optional `transport_allowlist` + optional `/pair <secret>` (`transport_require_allowlist`).

- **Discord** **[optional]** — full bot at `discord_bot/` (own `requirements.txt`, `bot.py`, music resolver, rich embeds). Tokens: `discord_bot_token`, `discord_webhook_url`.
- **Slack** **[optional]** — `transports/slack_bot.py`. `slack_bot_token`, `slack_app_token`, `slack_webhook_url`.
- **Telegram** **[optional]** — `transports/telegram_bot.py`. `telegram_bot_token`.
- **MCP (Model Context Protocol)** **[optional]**:
  - **Outbound MCP client** — `agent/services/mcp_client.py` + tool `mcp_tools_call` (stdio). `mcp_client_enabled` (default false), `mcp_stdio_servers`. Requires `allow_run` + dangerous-tool approval.
  - **Inbound MCP server (Cursor)** — `cursor-layla-mcp/server.py` exposes local Layla to Cursor over stdio; targets `LAYLA_BASE_URL` (default `http://127.0.0.1:8000`).
- **OpenAI-compatible API** — Layla also *serves* an OpenAI-compatible surface (`agent/routers/openai_compat.py`), so external clients can call it.
- **OpenClaw gateway** **[optional]** — `openclaw_gateway_url` (validated in `agent/services/system_doctor.py`); see `docs/OPENCLAW_ALIGNMENT.md`.

## Optional Bridges & Sync

All graceful no-ops when the daemon/key is absent; SQLite + Chroma remain the source of truth.

- **Obsidian** **[optional]** — `agent/services/obsidian_sync.py` + `agent/routers/obsidian.py`. Bidirectional vault ↔ `knowledge/` sync, local filesystem only, newer-mtime-wins.
- **Syncthing** **[optional]** — `agent/services/syncthing_sync.py`. REST at `http://127.0.0.1:8384`, `syncthing_api_key`, folder id `layla-data`. API key never logged.
- **Elasticsearch** **[optional, default off]** — `agent/services/elasticsearch_bridge.py`. `elasticsearch_enabled`, `elasticsearch_url` (`http://127.0.0.1:9200`), `elasticsearch_index_prefix`, `elasticsearch_api_key`. Mirrors learnings for keyword search.
- **Meilisearch** **[optional]** — `agent/services/meilisearch_bridge.py`.
- **mem0** **[optional]** — `agent/services/mem0_integration.py`.
- **Spotify** **[optional]** — `spotify_client_id` / `spotify_client_secret` (Discord music features).
- **External CAD/geometry bridge** **[optional]** — `geometry_external_bridge_url` for operator-hosted CAD (`fabrication_assist/`, geometry tools).

## Data Storage

**Databases (local, source of truth):**
- **SQLite** **[required]** — `agent/layla/memory/db_connection.py`; DB at `layla.db` under `LAYLA_DATA_DIR` (else repo root). Many tables/modules under `agent/layla/memory/*.py` (conversations, learnings, telemetry, plans, missions, tasks, capabilities) and `agent/layla/codex/codex_db.py`.
- **ChromaDB** **[required for semantic recall]** — persistent vector store (`agent/layla/memory/vector_store.py`). Can be disabled (`use_chroma: false`) on weak hardware. Optional Qdrant path exists (`agent/layla/memory/vector_qdrant.py`).
- **diskcache** + JSON sidecars — completion/HTTP/config caches.

**File Storage:**
- Local filesystem only, sandboxed under `sandbox_root` (default `~`). Per-workspace state under `.layla/` (file checkpoints, project memory, wiki, investigation reuse).

**Caching:**
- In-memory + diskcache (`completion_cache`, `response_cache`, `http_response_cache`). No external cache service.

## Authentication & Identity

- **Remote API key** — `remote_api_key`; enforced for non-loopback requests when `remote_enabled` (`agent/services/auth.py`).
- **Tunnel/pairing tokens** — `tunnel_auth.py` (token TTL), `/pair <secret>` for transports, mDNS pairing tokens.
- No external IdP/OAuth provider for the core app (Spotify OAuth is the lone provider, for music).

## Monitoring & Observability

- **OpenTelemetry** **[optional, default off]** — `agent/services/otel_export.py`, `opentelemetry_enabled`.
- **Langfuse** **[optional, default off]** — cloud LLM traces; `langfuse_enabled`, `langfuse_public_key`, `langfuse_secret_key`, `langfuse_host` (`agent/services/langfuse_export.py`).
- **Internal** — structured logging to `logs/`, SQLite telemetry (`telemetry_enabled`), metrics (`agent/services/metrics.py`, `observability.py`, `performance_monitor.py`), crash handler (`crash_handler.py`).

## CI/CD & Deployment

- **Hosting:** local single-host; `Dockerfile` + `docker-compose.yml` (sandbox-escaping `docker_run` flags blocked).
- **Updates** **[optional]** — `auto_update_check_enabled`, `github_repo` checked against GitHub Releases (`agent/services/auto_updater.py`).
- **Model download** — `agent/install/model_downloader.py` pulls GGUFs from Hugging Face (`huggingface_hub` when available, else resumable direct HTTP with atomic replace).

## Secrets Handling

- **Redaction on echo** — `agent/services/secret_filter.py` (`is_secret_key`) redacts credential keys (`*api_key*`, `*secret*`, `*password*`, `*_token`, `bot_token`, `auth_token`, …) from `/system_export` and `/settings` responses; carefully avoids redacting diagnostic keys like `completion_max_tokens`.
- Secrets read from `runtime_config.json` / env at call time and **never logged** (explicit comments in `syncthing_sync.py`, `secret_filter.py`).
- Credential config keys (all default null): `discord_bot_token`, `slack_bot_token`/`slack_app_token`, `telegram_bot_token`, `remote_api_key`, `elasticsearch_api_key`, `tailscale_auth_key`, `syncthing_api_key`, `spotify_client_*`, `langfuse_*_key`, `litellm_api_keys`.

## Webhooks & Callbacks

- **Incoming:** transport bot webhooks (Discord/Slack) when those bots are enabled; OpenAI-compatible + pairing/tunnel endpoints. None enabled by default.
- **Outgoing:** `discord_webhook_url` / `slack_webhook_url` notifications; LiteLLM/Langfuse callbacks when enabled.

---

*Integration audit: 2026-06-29*
