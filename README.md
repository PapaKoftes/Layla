# ∴ Layla

**Your own AI. On your machine. No cloud. No leash.**

Layla is a self-hosted AI companion and engineering agent. She runs entirely on your hardware using any GGUF model you choose — no API keys, no subscriptions, no data leaving your machine. She grows with you: she remembers things, studies topics on her own, uses tools, browses the web, and talks back if you want her to.

She has six distinct aspects (voices/personalities) you can switch between. She can write and run code, read and modify files, research repos, search the web, and hold a real conversation. She is designed to be as capable as any commercial AI assistant — and unlike those, she belongs entirely to you.

**Why Layla exists:** Built as a sovereign alternative to corporate AI — privacy-focused, local-first, anti-surveillance. Your data stays yours. See [VALUES.md](VALUES.md) for the principles behind the project.

---

## What makes her different

| | Layla | Commercial AI |
|---|---|---|
| Runs locally | ✓ | ✗ |
| Your data stays on your machine | ✓ | ✗ |
| Free forever | ✓ | ✗ (usually) |
| Works offline | ✓ | ✗ |
| You choose the model | ✓ | ✗ |
| Uncensored (you decide) | ✓ | ✗ |
| Persistent memory | ✓ | ✗ (mostly) |
| Grows her own knowledge | ✓ | ✗ |
| Open source | ✓ | ✗ |
| Voice I/O | ✓ | varies |
| Browser automation | ✓ | ✗ |
| Cursor / IDE integration | ✓ | limited |

---

## Install

**Prerequisite:** Python **3.11 or 3.12** only (3.13+ is not supported yet — dependency stack).

### Windows
1. Install Python 3.11 or 3.12 from [python.org](https://python.org) — check **"Add Python to PATH"**
2. Run **`install.ps1`** (PowerShell) or double-click **`INSTALL.bat`**
3. The installer detects your hardware, recommends a model, and can download it automatically
4. Double-click **`START.bat`** to launch → `http://localhost:8000/ui`

### Linux / macOS
```bash
git clone https://github.com/your-org/layla.git && cd layla
bash install.sh    # One command: venv, deps, Playwright, hardware wizard
bash start.sh     # Launch when ready
```

**Need Python 3.11 or 3.12?**
- Debian/Ubuntu: `sudo apt install python3.12 python3.12-venv` (or `python3.11` / `python3.11-venv`)
- Fedora: `sudo dnf install python3.12 python3-devel`
- macOS: `brew install python@3.12` (or `python@3.11`)

The installer automatically detects CPU, RAM, and GPU, recommends the best model for your hardware, and can download it to `~/.layla/models/`. If you skip the download, see [MODELS.md](MODELS.md) — put the `.gguf` in `~/.layla/models/` or `models/` and run `python agent/install/installer_cli.py` to configure.

---

## Getting a model

Layla needs a `.gguf` model file to work. Download one and put it in `models/`.

**Not sure which one?** Open [MODELS.md](MODELS.md) — it lists the best options for every hardware tier, with direct HuggingFace download links and one-line config snippets.

**Recommended starting point:**  
- 8 GB VRAM → [Qwen2.5-7B-Instruct-Q5_K_M](https://huggingface.co/bartowski/Qwen2.5-7B-Instruct-GGUF)  
- 16 GB VRAM → [Qwen2.5-14B-Instruct-Q5_K_M](https://huggingface.co/bartowski/Qwen2.5-14B-Instruct-GGUF)  
- Big GPU (24GB+) → [Qwen2.5-72B-Instruct-Q4_K_M](https://huggingface.co/bartowski/Qwen2.5-72B-Instruct-GGUF)  
- CPU only → [Llama-3.2-3B-Instruct-Q8_0](https://huggingface.co/bartowski/Llama-3.2-3B-Instruct-GGUF)

**For an uncensored experience:**  
[Dolphin](https://huggingface.co/mradermacher/dolphin-2.9-mistral-7b-v2-GGUF) or [Hermes](https://huggingface.co/bartowski/Hermes-3-Llama-3.1-8B-GGUF) — no content filtering, full knowledge access. Set `"uncensored": true` in `agent/runtime_config.json` (it's the default).

---

## Her voices (Aspects)

Switch between them in the sidebar or say their name:

| Aspect | Personality | Best for |
|---|---|---|
| **⚔ Morrigan** | Blunt engineer. No flattery. Fast. | Code, debugging, architecture |
| **✦ Nyx** | Deep researcher. Encyclopedic. Precise. | Research, explanations, analysis |
| **◎ Echo** | Companion. Mirrors your patterns. Grows with you. | Check-ins, reflection, context |
| **⚡ Eris** | Chaos energy. Banter. Games. Music. Feral wit. | Just talking, fun, ideas |
| **⌖ Cassandra** | Unfiltered oracle. Speaks truth before finishing the thought. | Raw reactions, first impressions, what nobody else noticed |
| **⊛ Lilith** | Core authority. Ethics. Full autonomy. | Deep questions, NSFW when you want it |

---

## What she can do

**Chat & reasoning**
- Streams replies in real time
- Remembers facts you tell her (persistent memory across sessions)
- Studies topics on her own between sessions (optional scheduler)
- Multi-aspect deliberation — inner voices debate before answering on complex questions
- Chain-of-thought reasoning built in
- Optional self-reflection: she scores her own answer and rewrites if it's not good enough

**Tools (she can use these herself)**
- Read, write, and edit files
- Run shell commands and Python
- Search the web (DuckDuckGo, no API key)
- Browse JS-heavy websites with Playwright
- Take screenshots of web pages
- Fill and submit forms
- Search your codebase with grep/glob
- Git operations (status, diff, log, branch)
- Apply patches

**Memory**
- Remembers things you tell her: facts, preferences, strategies
- Semantic recall: finds relevant past memories for the current topic
- Full-text keyword search over everything she's learned
- BM25 + vector hybrid search for the best possible recall
- Cross-encoder reranking: re-scores results for accuracy
- HyDE: generates a hypothetical answer, searches with that embedding
- Knowledge base: index any folder of `.md`, `.txt`, or `.pdf` files

**Voice (optional, install separately)**
- Mic input → faster-whisper transcription → auto-send
- Layla's replies are spoken back via kokoro-onnx (offline, high quality)

**Research & missions**
- Autonomous multi-stage repo research and analysis
- Staged missions: map → deep → full
- **Long-running missions** — Start research or engineering tasks via `POST /mission`; Layla runs steps in the background and persists progress across restarts. See [docs/missions.md](docs/missions.md).

---

## Architecture

```
┌─────────────────────────────────────────────────────────────────────────┐
│  Client (Web UI / CLI / MCP / TUI)                                       │
└──────────────────────────────┬──────────────────────────────────────────┘
                               │
┌──────────────────────────────▼──────────────────────────────────────────┐
│  FastAPI (localhost:8000)                                                │
│  /agent | /health | /wakeup | /approve | /v1 (OpenAI-compatible)         │
└──────────────────────────────┬──────────────────────────────────────────┘
                               │
┌──────────────────────────────▼──────────────────────────────────────────┐
│  Agent loop  │  Planner  │  Orchestrator (aspects)  │  Tool dispatcher   │
└──────────────┬────────────────────────────────────┬────────────────────┘
               │                                      │
┌──────────────▼──────────────┐    ┌─────────────────▼──────────────────┐
│  llama-cpp-python (GGUF)     │    │  Memory: SQLite + Chroma + NetworkX │
│  Model inference            │    │  Learnings, study_plans, audit      │
└─────────────────────────────┘    └─────────────────────────────────────┘
```

See [docs/LAYLA_SYSTEM_OVERVIEW.md](docs/LAYLA_SYSTEM_OVERVIEW.md) for the full architecture.

---

## Configure her

Everything is in `agent/runtime_config.json`. Run `agent/first_run.py` to have it generated for your hardware, or edit it manually:

```json
{
  "model_filename": "Qwen2.5-7B-Instruct-Q5_K_M.gguf",
  "n_ctx": 4096,
  "n_gpu_layers": -1,
  "completion_max_tokens": 256,
  "temperature": 0.2,
  "uncensored": true,
  "nsfw_allowed": true,
  "enable_cot": true,
  "sandbox_root": "C:/Users/you/projects"
}
```

See [MODELS.md](MODELS.md) for all config options.

**Enabling vector memory:** Set `"use_chroma": true` in `agent/runtime_config.json`. This enables semantic search over learnings and knowledge docs. ChromaDB indexes files in `knowledge/` at startup. Without it, Layla falls back to FTS (full-text search) and the knowledge graph.

---

## Add your own knowledge

Put `.md`, `.txt`, or `.pdf` files in the `knowledge/` folder. Layla indexes them automatically at startup and uses them when answering questions. This is how you give her specialized knowledge — docs, notes, manuals, codebases, anything.

---

## CLI commands

```
python layla.py wakeup           Session greeting + what she studied
python layla.py ask "message"    Send a message
python layla.py study "topic"    Add a study topic
python layla.py plans            List active study plans
python layla.py approve <uuid>   Approve a pending action
python layla.py pending          Show pending approvals
python layla.py export           Full system snapshot
```

---

## Approval system

When Layla wants to write files or run code, she asks first. You approve or deny:

- **Web UI:** Approvals panel (right sidebar)
- **CLI:** `python layla.py approve <uuid>`
- **API:** `POST http://localhost:8000/approve` with `{"id": "<uuid>"}`

---

## Cursor / IDE integration

Layla integrates with [Cursor](https://cursor.sh) via MCP. She becomes your coding copilot that actually knows your codebase and remembers your preferences.

See `.cursor/rules/layla-assistant.mdc` for full setup.

---

## Interfaces

| Interface | URL / Command |
|---|---|
| **Web UI** | http://localhost:8000/ui |
| **API docs** | http://localhost:8000/docs |
| **CLI** | `python layla.py` |
| **TUI** | `cd agent && python tui.py` |
| **OpenAI-compatible API** | `http://localhost:8000/v1` |
| **Open WebUI** | Point at `http://localhost:8000/v1` |
| **Discord bot** | `python -m discord_bot.run` — voice, TTS, music. See [discord_bot/README.md](discord_bot/README.md). |

---

## Documentation

| | |
|---|---|
| [VALUES.md](VALUES.md) | Project principles: sovereignty, privacy, anti-surveillance |
| [MODELS.md](MODELS.md) | Model recommendations, download links, config guide |
| [CONTRIBUTING.md](CONTRIBUTING.md) | How to contribute |
| [docs/RUNBOOKS.md](docs/RUNBOOKS.md) | First run, adding tools, aspects, knowledge |
| [docs/TECH_STACK_AND_CAPABILITIES.md](docs/TECH_STACK_AND_CAPABILITIES.md) | Full capability list |
| [docs/LAYLA_SYSTEM_OVERVIEW.md](docs/LAYLA_SYSTEM_OVERVIEW.md) | Architecture overview |
| [LICENSE](LICENSE) | Non-commercial source license |

---

## Common issues

- **Model not loading** — Check path in Settings, VRAM, `n_gpu_layers`. See [MODELS.md](MODELS.md).
- **Approvals not working** — Enable Allow Write / Allow Run in the sidebar.
- **Voice not working** — `pip install sounddevice` (CLI) or check browser mic permissions (UI).

---

## License

Layla is source-available and free for personal, educational, and non-commercial use.  
Commercial use requires permission. See [LICENSE](LICENSE).

Contributions welcome. See [CONTRIBUTING.md](CONTRIBUTING.md).
