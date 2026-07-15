<div align="center">

# Layla

**Your own AI. On your machine. No cloud. No leash.**

[![CI](https://github.com/PapaKoftes/Layla/actions/workflows/ci.yml/badge.svg)](https://github.com/PapaKoftes/Layla/actions/workflows/ci.yml)
![Python](https://img.shields.io/badge/python-3.11%20%7C%203.12-blue)
[![License](https://img.shields.io/badge/license-Source--available-lightgrey)](LICENSE)

<br/>

<img src="readme-assets/hero-layla-ui.png" alt="Layla Web UI — captured from local /ui" width="920"/>

<sub>PNG/GIF assets are generated from a real headless Chromium session: <code>python scripts/capture_readme_assets.py</code> · <a href="docs/media/README.md">docs/media/README.md</a></sub>

<br/>

**Local-first · Tool-heavy · Approval-gated · Six aspects · Voice & browser optional**

[Install](#install) · [Screenshots](#screenshots--demo) · [Features](#what-she-can-do) · [Docs](#documentation) · [Contributing](CONTRIBUTING.md)

</div>

---

Layla is a **local-first AI companion and engineering agent**. She runs on your hardware with any GGUF model you choose — no API keys or subscriptions required for core use. She remembers, studies, exposes a large native tool surface, can browse the web, and supports voice I/O.

**Positioning:** Layla is an open, self-hosted **agent platform** (HTTP API + Web UI + optional MCP), not a drop-in clone of a single vendor product — quality depends on your model, hardware, and config.

> **License note:** Layla is **source-available under a non-commercial license** — free for personal, educational, and non-commercial use; commercial/revenue-generating use needs permission. It is not an OSI open-source license. See [LICENSE](LICENSE).

**Why Layla exists:** A sovereign alternative to corporate AI — privacy-focused, local-first, anti-surveillance. See [VALUES.md](VALUES.md).

---

## Table of contents

- [Screenshots & demo](#screenshots--demo)
- [What makes her different](#what-makes-her-different)
- [Install](#install)
- [Getting a model](#getting-a-model)
- [Her voices (Aspects)](#her-voices-aspects)
- [What she can do](#what-she-can-do)
- [Built-in quality enforcement](#built-in-quality-enforcement)
- [Architecture](#architecture)
- [Configure her](#configure-her)
- [Add your own knowledge](#add-your-own-knowledge)
- [CLI commands](#cli-commands)
- [Approval system](#approval-system)
- [Cursor / IDE integration](#cursor--ide-integration)
- [Interfaces](#interfaces)
- [Documentation](#documentation)
- [Common issues](#common-issues)
- [License](#license)

---

## Screenshots & demo

| | |
|:--|:--|
| <img src="readme-assets/hero-layla-ui.png" alt="Chat and sidebar" width="440"/> | <img src="readme-assets/approvals-panel.png" alt="Approvals panel" width="440"/> |
| Chat-oriented Web UI (`/ui`) | Governance: pending writes & runs |

**GIF:** [demo.gif](readme-assets/demo.gif) — short scroll loop on `/ui` (regenerate via `scripts/capture_readme_assets.py`).
![Demo](readme-assets/demo.gif)

**Brand assets:** Aspect art lives under [`agent/ui/aspects/`](agent/ui/aspects/) (SVG).

---

## What makes her different

| | Layla | Typical cloud AI |
|---|---|---|
| Runs locally | Yes | No |
| Your data stays on your machine | Yes | No |
| No subscription for core use | Yes | Often no |
| Works offline (after model download) | Yes | No |
| You choose the model | Yes | No |
| Uncensored (operator-controlled) | Yes | No |
| Persistent memory (SQLite + vectors) | Yes | Rare |
| Open source / source-available | Yes | No |
| Voice I/O | Optional | Varies |
| Browser automation | Yes | Rare |
| Cursor / IDE via MCP | Yes | Limited |

---

## Install

### Not a programmer? Start here (no Git, no terminal)

1. On the [GitHub page](https://github.com/PapaKoftes/Layla), click the green **Code** button → **Download ZIP**, then unzip it (you do **not** need Git).
2. Open the unzipped folder and **double-click `INSTALL.bat`** (Windows) or **`install/Install Layla.command`** (macOS). It installs everything and picks a model for you — no build tools, no admin.
3. When it finishes it opens **http://127.0.0.1:8000/ui** in your browser. That's it — start chatting.

What to expect the first time: it **downloads a model (~2–5 GB)**, which can take **10–40 minutes** on a normal connection — the progress bar is normal, don't close the window. Windows **SmartScreen/antivirus** may warn about a new unsigned app or quarantine the model download; choose *More info → Run anyway* / allow it, or add the folder to your AV exclusions. If a step fails, the installer prints the exact cause and a fix.

> Developers / power users: the one-command CLI install and alternatives are below.

**First-time guide:** [docs/GETTING_STARTED.md](docs/GETTING_STARTED.md)

**10-minute green path** (health, `/ui`, first chat, optional approval): [docs/GOLDEN_FLOW.md](docs/GOLDEN_FLOW.md) — section *Ten-minute operator acceptance*.

**Prerequisite:** Python **3.11 or 3.12** (**3.13+** — including **3.14** — is not supported for the full dependency stack yet).

### Quickest — one command (installs Python **and** every dependency)

You do **not** need Python or any build tools first. [uv](https://docs.astral.sh/uv/) fetches a
standalone Python, installs **prebuilt CPU wheels** (no compiler on any OS), provisions a model for
your hardware, and runs a deep self-test.

**Windows** (PowerShell):

```powershell
git clone https://github.com/PapaKoftes/Layla.git
cd Layla
powershell -ExecutionPolicy Bypass -File install\bootstrap.ps1
.\layla.cmd            # then open http://127.0.0.1:8000/ui
```

**macOS / Linux:**

```bash
git clone https://github.com/PapaKoftes/Layla.git
cd Layla
./install/bootstrap.sh
./layla                # then open http://127.0.0.1:8000/ui
```

macOS users can also double-click **`install/Install Layla.command`**.
Options: `--prefer quality|balanced|lite|speed`, `--skip-model`, `--verify` (PowerShell:
`-Prefer`, `-SkipModel`, `-Verify`).

### Alternatives

- The repo-root **`install.sh`** (Linux/macOS) and **`install.ps1`** / **`INSTALL.bat`** (Windows) now run the same uv installer — use whichever entry point you prefer.
- **Prefer your own system Python + winget** (no uv): `powershell -ExecutionPolicy Bypass -File install\fresh_install.ps1` on Windows, which installs Python 3.12 via winget and uses the same compiler-free wheels.
- **Packaged Windows installer** (double-click `.exe`, embedded CPython): see [`installer/README.md`](installer/README.md). Runtime data may live under `%LOCALAPPDATA%\\Layla` via `LAYLA_DATA_DIR`. **A packaged `.app`/AppImage for macOS/Linux is not built yet** — on those platforms use the script installer above (`./install/bootstrap.sh`), which is the fully supported path.
- **Supply-chain / trust:** the bootstrap fetches [uv](https://docs.astral.sh/uv/) from `astral.sh` and downloads model GGUFs from Hugging Face. Downloads are verified by size + GGUF magic bytes, and by SHA-256 when the catalog entry carries one. In a locked-down environment, pre-install `uv` yourself and point the installer at a vetted model file instead of the curl-based bootstrap.

### Uninstall

- **Windows** — run **`uninstall.ps1`** (or `uninstall.bat`) from the repo root. It stops/removes the `LaylaSvc` service, the `Jinx Agent Server` scheduled task, the two firewall rules, the `LAYLA_INSTALL_ROOT` env var, and the `.venv`; it then offers to delete your data (`~/.layla`, models). If you used the packaged `.exe`, use its own entry in **Add/Remove Programs**.
- **Shared packages are NOT auto-removed** (they may be used by other software): Python 3.12 and, if you enabled the tunnel, `cloudflared` — the uninstaller prints the `winget uninstall` commands so you can remove them manually.
- **macOS/Linux** — delete the repo folder and `~/.layla`; no system services are installed.

---

## Getting a model

Layla needs a **`.gguf`** file. **The installer picks one for you** — it detects your hardware and
downloads a good fit, and the first-run wizard (Settings → Models) lets you change it, so most people
never do this by hand. The picks below are for advanced users choosing manually.

**Quick picks** (match to your use — the in-app picker surfaces both a companion default *and* a
`recommended_coding` pick so you're not steered to the wrong one):

- **Coding, CPU / ≤16 GB** → [Qwen2.5-Coder-7B-Instruct-Q4_K_M](https://huggingface.co/bartowski/Qwen2.5-Coder-7B-Instruct-GGUF) (or the **3B Coder** for ~2× the speed at equal benchmark quality — see [benchmarks](benchmarks/README.md))
- **Coding, ~8 GB+ GPU** → [Qwen2.5-Coder-7B/14B-Instruct](https://huggingface.co/bartowski/Qwen2.5-Coder-14B-Instruct-GGUF)
- **General chat / companion** → [Qwen2.5-7B-Instruct](https://huggingface.co/bartowski/Qwen2.5-7B-Instruct-GGUF) or an uncensored option in [MODELS.md](MODELS.md)

Place files under `models/` or `~/.layla/models/` and set `model_filename` in `agent/runtime_config.json` (or just use the in-app picker).

---

## Her voices (Aspects)

Switch in the sidebar or invoke by name:

| Aspect | Personality | Best for |
|--------|-------------|----------|
| **Morrigan** | Blunt engineer | Code, debug, architecture |
| **Nyx** | Deep researcher | Analysis, long explanations |
| **Echo** | Companion / mirror | Check-ins, patterns |
| **Eris** | Playful chaos | Banter, creativity |
| **Cassandra** | Unfiltered oracle | Hot takes, first impressions |
| **Lilith** | Core / ethics / NSFW gate | Sovereignty, intimate register |

---

## What she can do

**Conversation & reasoning**

- Streaming replies, persistent memory, optional study scheduler  
- Multi-aspect deliberation on complex prompts  
- Chain-of-thought and optional self-reflection  

**Tools (agent-invoked, gated)**

- File read/write/edit, patches, shell, Python  
- Web search, Playwright browser automation, screenshots  
- Repo search (grep/glob), Git operations  
- 198 registered tools — see [AGENTS.md](AGENTS.md) and [docs/TECH_STACK_AND_CAPABILITIES.md](docs/TECH_STACK_AND_CAPABILITIES.md)  

**Memory**

- SQLite + optional Chroma, hybrid retrieval, learnings, knowledge folder indexing  

**Voice (optional deps)**

- faster-whisper (STT), pyttsx3 (TTS — shipped default); optional kokoro-onnx (higher quality, GPLv3, opt-in via `layla[voice-kokoro]`)  

**Missions**

- Background research/engineering flows — [docs/missions.md](docs/missions.md)  

---

## Built-in quality enforcement

Layla includes **deterministic** checks (tool outputs, plan pre-validation, completion gate, validation matrix) to improve reliability on smaller local models. For full behavior, set in your real **`runtime_config.json`**:

```json
{
  "completion_gate_enabled": true,
  "deterministic_tool_routes_enabled": true
}
```

See [docs/GETTING_STARTED.md](docs/GETTING_STARTED.md#quality-enforcement-recommended) and `agent/runtime_config.example.json`. Architecture summary: [ARCHITECTURE.md](ARCHITECTURE.md).

### Coding benchmarks — measured, not asserted

`scripts/benchmark_coding.py` scores deterministic **pass@1** (temperature 0, seed 42) on two tiers: **core** (10 canonical fundamentals) and **hard** (12 discriminating LeetCode medium/hard — LCS, edit distance, nested `decode_string`, `three_sum`, spiral order, `next_permutation`, …). Latest, on the reference CPU laptop (4-core / ~16 GB / no-GPU):

| Model | core pass@1 | hard pass@1 | tok/s (core / hard) |
|---|---|---|---|
| Qwen2.5-Coder-7B-Q4 *(default)* | **100 % (10/10)** | **100 % (12/12)** | 3.4 / 4.2 |
| Qwen2.5-Coder-3B-Q4 *(`-Prefer lite`)* | **100 % (10/10)** | **100 % (12/12)** | 6.6 / 9.6 |

Both models pass **22/22**; the 3B matches the 7B at ~2× the speed on a CPU-only laptop. Per-problem scorecards and honest caveats: **[benchmarks/README.md](benchmarks/README.md)**. A **nightly CI job** re-runs both tiers against a real model with a regression floor, so these numbers stay current as the project evolves. Regenerate locally:

```bash
python scripts/benchmark_coding.py --model models/<model>.gguf                 # core
python scripts/benchmark_coding.py --hard --model models/<model>.gguf          # hard tier
python scripts/benchmark_coding.py --self-test                                 # validate the harness (no model)
```

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
│  llama-cpp-python (GGUF)   │    │  Memory: SQLite + Chroma + graph   │
│  Model inference            │    │  Learnings, plans, audit           │
└─────────────────────────────┘    └────────────────────────────────────┘
```

Deeper dive: [docs/LAYLA_SYSTEM_OVERVIEW.md](docs/LAYLA_SYSTEM_OVERVIEW.md), [ARCHITECTURE.md](ARCHITECTURE.md).

---

## Configure her

Primary config: **`agent/runtime_config.json`** (or `%LAYLA_DATA_DIR%/runtime_config.json` when set). The installer writes this for you. To hand-edit, start from **`agent/runtime_config.minimal.example.json`** — the ~8 keys most people ever touch (model, sandbox, context size, limits). The full **`agent/runtime_config.example.json`** is the ~400-key reference for everything else; you don't need most of it, and writes/exec stay off-by-default regardless.

```json
{
  "model_filename": "Qwen2.5-7B-Instruct-Q5_K_M.gguf",
  "n_ctx": 4096,
  "n_gpu_layers": -1,
  "completion_max_tokens": 256,
  "temperature": 0.2,
  "uncensored": true,
  "completion_gate_enabled": true,
  "deterministic_tool_routes_enabled": true,
  "sandbox_root": "C:/Users/you/projects"
}
```

Full key reference: [docs/CONFIG_REFERENCE.md](docs/CONFIG_REFERENCE.md). Model help: [MODELS.md](MODELS.md).

**Vector memory:** `"use_chroma": true` enables semantic search over learnings and `knowledge/` (indexed at startup).

---

## Add your own knowledge

Add `.md`, `.txt`, or `.pdf` under **`knowledge/`** (see `.gitignore` for curated exceptions). Layla indexes on startup fingerprint change.

---

## CLI commands

> **Two different `layla` entry points:** `layla.cmd` / `./layla` **start the server** (they wrap
> `serve.py`). The **command CLI** is `python layla.py <command>` — that's what runs the commands below.
> `layla.cmd doctor` will *not* run diagnostics (it passes `doctor` to the server launcher); use
> `python layla.py doctor` instead.

```text
python layla.py wakeup           Session greeting + study summary
python layla.py ask "message"    Send a message
python layla.py study "topic"    Add a study topic
python layla.py plans            List study plans
python layla.py approve <uuid>  Approve pending action
python layla.py pending          Pending approvals
python layla.py export           System snapshot
```

---

## Approval system

Mutating tools and dangerous operations can require approval:

- **Web UI:** Approvals panel  
- **CLI:** `python layla.py approve <uuid>`  
- **API:** `POST http://localhost:8000/approve` with `{"id": "<uuid>"}`  

---

## Cursor / IDE integration

Cursor integration via MCP — see [.cursor/rules/layla-assistant.mdc](.cursor/rules/layla-assistant.mdc) and [cursor-layla-mcp/](cursor-layla-mcp/).

---

## Interfaces

| Surface | URL / command |
|---------|----------------|
| **Web UI** | http://localhost:8000/ui |
| **OpenAPI** | http://localhost:8000/docs |
| **CLI** | `./layla` (Linux/macOS) · `layla.cmd` (Windows) · `layla --help` for flags |
| **TUI** | `cd agent && python tui.py` |
| **OpenAI-compatible** | `http://localhost:8000/v1` |
| **Discord** | [discord_bot/README.md](discord_bot/README.md) |

**Languages:** the web interface is translatable into 11 languages (English, Spanish,
German, French, Italian, Portuguese, Russian, Japanese, Chinese, Korean, Arabic — with
right-to-left layout for Arabic) — switch it in **Settings → Interface language**. Untranslated
strings fall back to English. Separately, set `response_language` to have the model *reply* in
your language.

---

## Documentation

**Hub:** [docs/README.md](docs/README.md) — full index (architecture, security, runbooks, roadmap).

| | |
|---|---|
| [VALUES.md](VALUES.md) | Principles |
| [MODELS.md](MODELS.md) | Models & config |
| [docs/OPENAI_COMPAT.md](docs/OPENAI_COMPAT.md) | `/v1` OpenAI-compatible API — supported vs not |
| [CONTRIBUTING.md](CONTRIBUTING.md) | Contribute |
| [docs/ONBOARDING_15_MIN.md](docs/ONBOARDING_15_MIN.md) | **15-minute** first-run checklist |
| [docs/GETTING_STARTED.md](docs/GETTING_STARTED.md) | First run (detailed) |
| [docs/SECURITY.md](docs/SECURITY.md) | Security |
| [docs/RUNBOOKS.md](docs/RUNBOOKS.md) | Operations |
| [agent/docs/audit/](agent/docs/audit/) | Subsystem audit & migration tracking |
| [agent/scripts/README.md](agent/scripts/README.md) | Health check scripts (12 checks, 3,000+ tests) |
| [LICENSE](LICENSE) | Non-commercial source license |

---

## Common issues

- **Model not loading** — Path, VRAM, `n_gpu_layers`. See [MODELS.md](MODELS.md).  
- **Approvals** — Enable Allow Write / Allow Run in the UI when you intend tool use.  
- **Voice** — Optional deps; browser mic permissions for UI.  
- **Tests** — `cd agent && pytest tests/ -m "not slow and not e2e_ui and not browser_smoke and not voice_smoke and not gpu_smoke"` (see [docs/VERIFICATION.md](docs/VERIFICATION.md) for deep jobs).  

---

## License

Layla is released under the **Layla Non-Commercial Source License** — free for personal, educational, and non-commercial use; commercial use requires permission. See [LICENSE](LICENSE).

Contributions welcome: [CONTRIBUTING.md](CONTRIBUTING.md).
