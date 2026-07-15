# Layla — 15-minute onboarding

Single-path checklist for a **first-time operator** on Windows (source install). Budget **~15 minutes** including downloads; model fetch time depends on your network and catalog choice.

For deeper detail: [GETTING_STARTED.md](GETTING_STARTED.md), [MODELS.md](../MODELS.md), [VERIFICATION.md](VERIFICATION.md).

---

## Before you start (2 min)

| Need | Notes |
|------|--------|
| **Python 3.11+** on PATH | From [python.org](https://www.python.org/downloads/); enable **Add Python to PATH**. |
| **Git clone** of this repo | You are reading it — good. |
| **Disk** | Reserve several GB for dependencies + at least one GGUF (size depends on model). |
| **Network** | Required for first-time `pip` and any catalog download; optional later if you only use a local `.gguf`. |

### Environment: Python 3.14+ and Chroma (warning)

If you use **Python 3.14 or newer**, you may see a **Chroma / Pydantic v1** compatibility warning at import time (often: *“Core Pydantic V1 functionality isn't compatible with Python 3.14 or greater”*). This comes from **upstream Chroma + Python**, not Layla application logic. It is usually **non-fatal**; semantic memory may still work. If Chroma fails during setup, `setup_layla` can fall back or repair (see `[setup]` lines). For the fewest surprises, prefer **Python 3.11 or 3.12** on Windows until the ecosystem catches up.

---

## Minutes 0–5: Install environment

1. Get the repo folder (Download ZIP + unzip, or `git clone`) — the folder that contains `INSTALL.bat` and `agent/`.
2. **Double-click `INSTALL.bat`** (or `.\INSTALL.bat` in a terminal there). It's powered by uv — no need to install Python first.
3. It creates **`.venv`**, installs prebuilt CPU wheels (no compiler), **detects your hardware and downloads a fitting model**, writes `runtime_config.json`, and runs a **deep self-test** (a real inference turn). Then start with **`.\layla.cmd`** → **http://127.0.0.1:8000/ui**.

**Advanced (own Python + winget, no uv):** `powershell -ExecutionPolicy Bypass -File install\fresh_install.ps1` (installs Python 3.12 via winget, same compiler-free wheels). Browser tools (Playwright) are optional and not installed by default.

**CI / unattended:** the uv bootstrap accepts `--prefer lite|balanced|quality|speed` and `--skip-model`; see [GETTING_STARTED.md](GETTING_STARTED.md).

---

## Minutes 5–10: Model on disk

- **Installer path:** Follow prompts; the catalog lives at `agent/models/model_catalog.json`.
- **Manual path:** Place a `.gguf` under a scanned `models/` directory and set **`model_filename`** (basename only) in **`agent/runtime_config.json`** — see [MODELS.md](../MODELS.md).

Partial HTTP downloads use **`.gguf.part`** + **`.part.meta`**; do not delete those while a download is active if you want resume.

---

## Minutes 10–15: Run and sanity-check

1. **Web UI:** open **http://127.0.0.1:8000/ui** (port from `runtime_config.json` if overridden).
2. **`GET /health`** — model pending / ready flags and softened warnings during background download are documented in [GETTING_STARTED.md](GETTING_STARTED.md).
3. One chat turn in the UI to confirm the agent responds.

**Automated gate (optional, from `agent/`):**

```bash
cd agent
python -m pytest tests/ -m "not slow and not e2e_ui and not browser_smoke and not voice_smoke and not gpu_smoke" --timeout=60
```

See [VERIFICATION.md](VERIFICATION.md) for CI parity and optional smokes.

---

## Optional roadmap (not in this release)

These are **future UX** items; they do not block core local use today.

| Item | Note |
|------|------|
| **UI download progress** | Rich progress in the browser for large GGUF downloads (today: terminal + `/health` / setup status). |
| **Model switching** | First-class UI flow to swap GGUFs without hand-editing config (today: `runtime_config.json` + catalog/setup). |

---

## Where things live

| Artifact | Typical location |
|----------|------------------|
| Config | `agent/runtime_config.json` (from `runtime_config.example.json`; gitignored if local) |
| Models | Repo `models/` / `agent/models/` / `%LOCALAPPDATA%\Layla\models` / `models_dir` in config — see [MODELS.md](../MODELS.md) |
| SQLite memory | `agent/layla.db` (after first run) |
| Chroma index | `agent/layla/memory/chroma_db/` when enabled |

Full key reference: [CONFIG_REFERENCE.md](CONFIG_REFERENCE.md).

---

## Troubleshooting (quick)

**Windows — cannot delete `.venv` (“access denied”)** — Another process still has DLLs open (Layla server, IDE terminal, antivirus). Quit Layla/Uvicorn, close terminals that activated the venv, then retry. Alternatively **rename** `.venv` to `.venv.old`, run `python -m venv .venv`, and reinstall with `pip install -r agent/requirements.txt`.
