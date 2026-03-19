# OpenClaw alignment — feature matrix

OpenClaw ([openclaw/openclaw](https://github.com/openclaw/openclaw)) is a **Node/TypeScript** personal assistant (Gateway, 20+ chat channels, OAuth models, `onboard` / `doctor`). Layla is **Python/FastAPI** with local GGUF, SQLite, Chroma, Web UI, and optional **transports** (Slack, Telegram) plus **discord_bot**.

There is **no shared codebase** to merge. This document maps concepts and where Layla implements or defers them.

| OpenClaw area | OpenClaw behavior | Layla status | Notes |
|---------------|-------------------|--------------|--------|
| Runtime | Node ≥22, npm global CLI | **N/A** | Python 3.11+, `uvicorn`, `layla.py` |
| Gateway / control plane | Daemon on port ~18789 | **Partial** | FastAPI `localhost:8000`; optional [OPENCLAW_BRIDGE.md](OPENCLAW_BRIDGE.md) HTTP sidecar |
| Multi-channel (WhatsApp, Signal, …) | Built-in | **Partial** | Slack/Telegram [`transports/`](../transports/); Discord [`discord_bot/`](../discord_bot/) |
| DM / inbound security | Pairing, allowlists, `dmPolicy` | **Partial** | Env/config allowlist + optional `/pair` secret — [`transports/base.py`](../transports/base.py) |
| Models | OAuth, API keys, failover docs | **Partial** | Local GGUF + optional remote; [`inference_router.py`](../agent/services/inference_router.py), `runtime_config.json` |
| Onboarding | `openclaw onboard` | **Done** | Web setup UI, `first_run.py`, `START.bat` |
| Diagnostics | `openclaw doctor` | **Done** | `system_doctor.py`, `/doctor`, `layla.py doctor`; optional gateway URL check |
| Skills / tools | Plugin model | **Done** | `layla/tools/registry.py`, plugins, approvals |
| MCP / IDE | Various | **Done** | `cursor-layla-mcp/server.py` |
| Canvas / voice apps | Rich clients | **Partial** | Web UI, Discord voice/TTS, optional Whisper |

**Sidecar**: Run OpenClaw Gateway **next to** Layla and POST user text to `POST /agent` — see [OPENCLAW_BRIDGE.md](OPENCLAW_BRIDGE.md).

## Model / inference routing (Layla, not OpenClaw-style auto-failover)

OpenClaw documents model failover across providers. Layla picks **one** backend per config via `agent/services/inference_router.py` (no silent “try remote then fall back to GGUF” loop unless you add it).

| `inference_backend` | Behavior |
|---------------------|----------|
| `llama_cpp` | Local GGUF via `llama-cpp-python` (`model_filename`, `models_dir`). |
| `openai_compatible` | HTTP `llama_server_url` + `/v1/chat/completions` (vLLM, LiteLLM, etc.). |
| `ollama` | Same URL style; Ollama heuristics (port `11434` or hostname contains `ollama`). |
| `auto` (default) | Explicit non-auto value wins. Else: **no** `llama_server_url` → `llama_cpp`; URL looks like Ollama → `ollama`; else → `openai_compatible`. |

Config keys: `inference_backend`, `llama_server_url`, `remote_model_name`, `remote_enabled` (governance elsewhere). Template: `agent/runtime_config.example.json`.

**North Star**: Do not change `LAYLA_NORTH_STAR.md` for alignment; update `docs/IMPLEMENTATION_STATUS.md` when features ship.

---

## Core agent, tools, and skills (ignoring gateway & channels)

This section is for **parity with OpenClaw’s agent/model/capability layer** only. Sources: [OpenClaw Tools](https://docs.openclaw.ai/tools), [Skills](https://openclaws.io/docs/tools/skills), [Agents overview](https://www.openclawdoc.com/docs/agents/overview/) (filtered to concepts that are not “50+ channels”).

### Tool governance — **implemented**

| OpenClaw idea | Layla implementation |
|---------------|----------------------|
| `tools.allow` / `tools.deny`, `group:*`, deny `*` | [`agent/services/tool_policy.py`](../agent/services/tool_policy.py) — `tools_profile`, `tools_allow`, `tools_deny`, `tool_groups`, optional `tools_by_provider`; wired in [`agent/agent_loop.py`](../agent/agent_loop.py) `_get_tools_for_goal` + **pre-exec guard** |
| Profiles `full` / `coding` / `messaging` / `minimal` | Same module; intersected with intent routing when `tool_routing_enabled` |

### Reliability & loops — **implemented**

| OpenClaw idea | Layla implementation |
|---------------|----------------------|
| Loop detection (repeat, ping-pong) | [`agent/services/tool_loop_detection.py`](../agent/services/tool_loop_detection.py); config `tool_loop_*`; WARN → next decision hint, STOP → blocked step |

### Execution & web — **implemented**

| OpenClaw idea | Layla implementation |
|---------------|----------------------|
| Background shell sessions | Tools `shell_session_start` (approval) + `shell_session_manage` (poll/log/kill) — [`agent/services/shell_sessions.py`](../agent/services/shell_sessions.py) |
| HTTP TTL cache | [`agent/services/http_response_cache.py`](../agent/services/http_response_cache.py); `http_cache_ttl_seconds` > 0 enables cache on `fetch_url` / `ddg_search` |
| Browser profiles | `browser_persistent_profiles` + `browser_default_profile` → Playwright `launch_persistent_context` under `agent/.browser_profiles/` — [`agent/services/browser.py`](../agent/services/browser.py) |

### Memory & “sessions” as tools

| OpenClaw idea | Layla implementation |
|---------------|----------------------|
| `memory_search` / `memory_get` | Registry aliases to `search_memories` pipeline — [`agent/layla/tools/registry.py`](../agent/layla/tools/registry.py) |
| Multi-agent **sessions** tools | Not implemented (aspects + single history; add only if needed) |

### Skills packaging — **implemented** (markdown)

| OpenClaw idea | Layla implementation |
|---------------|----------------------|
| `SKILL.md` + frontmatter, `requires` bins/env | [`agent/services/markdown_skills.py`](../agent/services/markdown_skills.py); default scan repo [`skills/`](../skills/) or override `markdown_skills_dir`; merged via `get_skills_prompt_hint()` in planner |
| Skill watch | Config key `markdown_skills_watch` reserved; **not** wired (restart to reload) |

### Model-adjacent — **implemented** (partial)

| OpenClaw idea | Layla implementation |
|---------------|----------------------|
| Image model split | `image_model` in config overrides BLIP id for `describe_image`; `image_generation_model` reserved |
| LLM Task / structured step | Tool `structured_llm_task` — one bounded JSON-oriented completion |
| Remote fallback URLs | `inference_fallback_urls` — non-stream OpenAI-compatible requests try next URL on 5xx / connection failure — [`agent/services/inference_router.py`](../agent/services/inference_router.py) |

### Summary

- **Patterns emulated in Python** (not OpenClaw code): tool policy, loop guard, shell sessions, HTTP cache, persistent browser profile, markdown skills, memory aliases, structured LLM tool, inference fallbacks.
- **Config template:** [`agent/runtime_config.example.json`](../agent/runtime_config.example.json) (`tools_*`, `tool_loop_*`, `http_cache_*`, `inference_fallback_urls`, `browser_*`, `markdown_skills_*`, `image_model`).
- **Tests:** [`agent/tests/test_openclaw_emulation.py`](../agent/tests/test_openclaw_emulation.py).

For implementation status of Layla modules, see [IMPLEMENTATION_STATUS.md](IMPLEMENTATION_STATUS.md).
