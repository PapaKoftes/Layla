# Layla

**Layla** is a local AI engineering companion: one consciousness, many aspects (Morrigan, Nyx, Echo, Eris, Lilith, Neuro). She runs on your machine using a **GGUF model** (llama-cpp-python), keeps memory in SQLite and an optional vector store, and exposes a FastAPI server for chat, tools, study plans, and research missions. Lilith can respond in an NSFW register when you use a keyword (e.g. intimate, nsfw) in your message.

- **Local-first:** Your model, your data, your machine.
- **Multi-aspect:** Different “voices” for code, research, reflection, banter, and ethics.
- **Approval-gated:** File writes and code execution require explicit approval.

---

## Quick start

1. **Clone the repo**
   ```bash
   git clone https://github.com/your-org/layla.git
   cd Layla
   ```

2. **Python and dependencies**  
   Use Python 3.10+. Create a venv and install:
   ```bash
   python -m venv .venv
   .venv\Scripts\activate   # Windows
   # source .venv/bin/activate   # Linux/macOS
   pip install -r agent/requirements.txt
   ```

3. **Get a GGUF model and configure Layla**  
   You need a local GGUF model (e.g. from Hugging Face or TheBloke).  
   - **Where to get it, how to choose for your hardware, and how to install:** [docs/GETTING_THE_MODEL.md](docs/GETTING_THE_MODEL.md)  
   - Put the `.gguf` file in the **`models/`** folder at the repo root.  
   - Copy `agent/runtime_config.example.json` to `agent/runtime_config.json` if needed, and set **`model_filename`** to your model file name (e.g. `my-model.Q4_K_M.gguf`).

4. **Start the server**
   ```bash
   cd agent
   uvicorn main:app --host 127.0.0.1 --port 8000
   ```

5. **Use Layla**  
   - Web UI: http://localhost:8000/ui  
   - CLI: `python layla.py wakeup` then `python layla.py ask "your message"`  
   - TUI: `cd agent && python tui.py`  
   - Interactive API docs: http://localhost:8000/docs

Full first-run steps (config, database, optional remote): [docs/RUNBOOKS.md#first-run](docs/RUNBOOKS.md#first-run).

---

## Pinned versions and paths

- **Python:** 3.10+ (tested 3.10–3.12). Dependencies: `agent/requirements.txt`.
- **Database:** SQLite at **repo root** `layla.db`. Created on first use. Path is fixed in `agent/layla/memory/db.py`.
- **Config:** `agent/runtime_config.json` (create from `agent/runtime_config.example.json` if missing).

---

## Main commands (CLI)

| Command | Description |
|--------|-------------|
| `python layla.py wakeup` | Session greeting and study status |
| `python layla.py ask "message"` | Send a message to Layla |
| `python layla.py study "topic"` | Add a study plan topic |
| `python layla.py plans` | List study plans |
| `python layla.py approve <uuid>` | Approve a pending action |
| `python layla.py pending` | List pending approvals |
| `python layla.py export` | System snapshot (config, tools, aspects) |

---

## Documentation

| Doc | Description |
|-----|-------------|
| [ARCHITECTURE.md](ARCHITECTURE.md) | One-page data flow, request path, where state lives |
| [docs/RUNBOOKS.md](docs/RUNBOOKS.md) | First run, add tool, add aspect, add knowledge, trace ID, proactive suggestions |
| [docs/GETTING_THE_MODEL.md](docs/GETTING_THE_MODEL.md) | **Where to get the GGUF model, how to choose for your hardware, download, install, and configure** |
| [docs/ROADMAP.md](docs/ROADMAP.md) | Full plan and roadmap (extensible) |
| [docs/TECH_STACK_AND_CAPABILITIES.md](docs/TECH_STACK_AND_CAPABILITIES.md) | Tech stack, current and planned capabilities |
| [docs/LAYLA_SYSTEM_OVERVIEW.md](docs/LAYLA_SYSTEM_OVERVIEW.md) | What Layla is, how she works, what you can do |
| [docs/MILESTONES.md](docs/MILESTONES.md) | M1–M6 milestones and status |
| [docs/REMOTE_ARCHITECTURE.md](docs/REMOTE_ARCHITECTURE.md) | Remote trigger (wakeup, one-shot) with auth |

---

## Approvals

When Layla needs to write files, run code, or run shell commands, she returns an `approval_required` response. Approve via:

- **CLI:** `python layla.py approve <uuid>`
- **TUI:** `/approve <uuid>`
- **Web UI:** Approvals panel → Approve
- **API:** `POST http://localhost:8000/approve` with `{"id": "<uuid>"}`

---

## MCP (Cursor)

Use the `cursor-layla-mcp` server to call Layla from Cursor: `chat_with_layla`, `add_learning`, `start_study_session`, etc. See `.cursor/rules/layla-assistant.mdc` for aspects, triggers, and approval flow.

---



---

## Using Open WebUI (optional)

Layla exposes an OpenAI-compatible `/v1/chat/completions` endpoint. Point [Open WebUI](https://github.com/open-webui/open-webui) at `http://localhost:8000/v1` for a full-featured chat UI with no extra code.

Open `http://localhost:3000` and select the `layla` model.

---

## License and contributing

See [LICENSE](LICENSE), [CONTRIBUTING.md](CONTRIBUTING.md), [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md). For security issues see [SECURITY.md](SECURITY.md).
