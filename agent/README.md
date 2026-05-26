# Layla

A locally-sovereign, multi-aspect AI agent with persistent memory, multi-provider LLM support, and a Warframe-inspired web UI.

## Quick Start

```bash
cd agent
python -m venv venv
venv\Scripts\activate        # Windows
# source venv/bin/activate   # Linux/Mac

pip install -r requirements.txt   # Full install (~4GB)
# pip install -e ".[core]"        # Core only (~250MB) — see docs/INSTALL_PROFILES.md

python main.py
# Open http://127.0.0.1:8000/ui
```

## What Layla Does

**6-Aspect Personality System** — Switch between specialized voices:
- **Morrigan** — Software engineering, debugging, architecture
- **Nyx** — Research, analysis, deep technical synthesis
- **Echo** — Empathy, communication, pattern recognition
- **Eris** — Creative ideation, brainstorming, unconventional approaches
- **Cassandra** — Rapid critique, blunt feedback, anomaly detection
- **Lilith** — Safety, ethics, boundary enforcement

**Persistent Memory** — SQLite + ChromaDB semantic search. Learnings, knowledge base, conversation history, and spaced repetition study system survive across sessions.

**Multi-Aspect Deliberation** — For complex questions, multiple aspects can debate, critique each other, and synthesize a unified response. Modes: solo, auto, debate (2 aspects), council (3), tribunal (all 6).

**Tool Execution** — File operations, code execution, web search, research missions, and structured engineering pipelines with operator approval gates.

**Multi-Provider LLM** — Local GGUF via llama.cpp, Ollama, OpenAI-compatible APIs, or Anthropic Claude via LiteLLM gateway with automatic provider health tracking and fallback.

**Maturity-Gated Autonomy** — XP system unlocks capabilities as trust is earned. Fresh installs start cautious; experienced instances gain more autonomy.

## Features

| Category | What's Built |
|----------|-------------|
| Agent Loop | 910-line orchestrator with tool dispatch, safety checks, plan/execute modes |
| Memory | SQLite + ChromaDB + knowledge base + spaced repetition + semantic recall |
| UI | Three-panel Warframe-themed web interface with SSE streaming, mobile responsive |
| Discord | 20+ slash commands, per-guild config, rich embeds, error handling |
| Remote Access | Cloudflared tunnels, hashed token auth, IP allowlist, audit logging |
| LLM Gateway | LiteLLM multi-provider with health circuit breaker and cost tracking |
| Skill Packs | Install custom tool packs from Git with manifest validation and sandboxing |
| Search | Meilisearch + Elasticsearch + SQLite FTS fallback chain |
| Research | Deep research missions with web crawling, PDF parsing, ArXiv/Wikipedia |
| Voice | Kokoro TTS + Faster Whisper STT, per-aspect voice settings |
| Scheduler | APScheduler with 11 background jobs (memory consolidation, study review, health checks) |
| MCP | Model Context Protocol client and server for tool interop |
| Safety | Dignity engine, content guard, approval gates, trust tiers, audit trail |

## Project Structure

```
agent/
  main.py                 # FastAPI server, middleware, lifespan
  agent_loop.py           # Core agent orchestrator (910 lines)
  runtime_safety.py       # Config, sandboxing, safety defaults
  config_schema.py        # Editable settings schema for /settings API
  core/
    executor.py           # Tool execution with tracing and cost tracking
    orchestrator.py       # Prompt building, aspect routing, deliberation
  layla/
    memory/               # SQLite DB, migrations, learnings, knowledge
    tools/                # Tool registry and built-in tool implementations
  services/               # 19 subdirectories, 216 modules, backward-compat shims at top level
    agent/                # Task runner, conversation manager, session context
    cluster/              # Multi-device clustering, mDNS discovery, node sync
    context/              # Conversation context, token budget, window management
    governance/           # Rate limiting, cost tracking, usage policies
    infrastructure/       # Core infra: config, logging, scheduling, caching, tunnels
    llm/                  # LLM gateway, inference routing, model management
    memory/               # Consolidation, curiosity, knowledge graphs, people codex
    observability/        # Metrics, tracing, health monitoring
    personality/          # Aspect behavior, maturity engine, style profiles
    planning/             # Goal decomposition, plan execution, task tracking
    prompts/              # Prompt building, compression, tier budgets
    reasoning/            # Debate engine, deliberation, multi-aspect synthesis
    retrieval/            # Search routing, semantic recall, web crawling
    safety/               # Dignity engine, content guard, approval gates
    sandbox/              # Code execution sandboxing and validation
    skills/               # Skill pack management and tool generation
    tools/                # Tool registry, MCP client/server
    user/                 # Onboarding, user preferences
    workspace/            # File operations, project management
  routers/
    agent.py              # POST /agent — main chat endpoint with SSE streaming
    system.py             # GET /health, /doctor, /tunnel/*
    settings.py           # GET/POST /settings, /settings/schema
    debate.py             # POST /debate, GET /debate/modes
    memory.py             # Memory CRUD and search
  ui/
    css/layla.css          # Main stylesheet (2,200+ lines, Warframe theme)
    js/                    # 16 ES modules (8,000+ lines)
    index.html             # Three-panel SPA
  tests/                   # 11,000+ test functions
  docs/                    # Setup guides, ADRs, vision roadmap
discord_bot/
  bot.py                   # Discord bot with 20+ slash commands
  rich_embeds.py           # Per-aspect themed embeds
  guild_config.py          # Per-server configuration
```

## Configuration

All settings live in `runtime_config.json` (auto-created on first run). Key settings:

```json
{
  "model_filename": "your-model.Q4_K_M.gguf",
  "sandbox_root": "C:/Users/you/LaylaWorkspace",
  "temperature": 0.2,
  "deliberation_mode": "auto",
  "safe_mode": true,
  "use_chroma": true,
  "litellm_enabled": false,
  "tunnel_enabled": false,
  "discord_bot_autostart": false
}
```

Edit via the web UI (Settings tab) or directly in the file.

## Install Profiles

| Profile | Size | Use Case |
|---------|------|----------|
| Core | ~250MB | Chat agent, memory, tools |
| Voice | +350MB | Text-to-speech + speech recognition |
| ML | +2GB | Image captioning, OCR |
| Research | +50MB | PDF parsing, ArXiv, Wikipedia |
| Crawl | +200MB | Web crawling with Playwright |
| All | ~4GB | Everything |

See [docs/INSTALL_PROFILES.md](docs/INSTALL_PROFILES.md) for details.

## Documentation

- [Vision & Roadmap](docs/VISION.md) — Full gap closure and product unification plan
- [Discord Bot Setup](docs/DISCORD_SETUP.md)
- [Remote Access / Tunnels](docs/REMOTE_ACCESS.md)
- [Skill Packs](docs/SKILL_PACKS.md)
- [Install Profiles](docs/INSTALL_PROFILES.md)
- [Architecture Decision Records](docs/adr/) — ADR-001 through ADR-006

## API

The server exposes a REST + SSE API at `http://127.0.0.1:8000`:

- `POST /agent` — Send a message (supports SSE streaming)
- `GET /health` — System status, model info, resource usage
- `GET /settings` — Current configuration
- `POST /settings` — Update configuration
- `POST /debate` — Direct deliberation endpoint
- `GET /conversations` — List conversations
- `GET /memory/learnings` — Browse learned knowledge
- `GET /doctor` — Diagnostic self-check

Full OpenAPI docs at `http://127.0.0.1:8000/docs`.

## Running Tests

```bash
cd agent
python -m pytest tests/ -x -q --timeout=30
```

## License

Proprietary. All rights reserved.
