# Technology Stack

**Analysis Date:** 2026-06-30

Layla is a local-first, multi-aspect AI companion / engineering agent (v1.4.0 "Castilla", a Spanish bilingual release). The runtime is a FastAPI HTTP server (`agent/main.py`, `agent/serve.py`) that drives an agentic tool-calling loop (`agent/agent_loop.py`) over a local GGUF model, with SQLite + ChromaDB as the memory substrate. Heavy ML dependencies are split into optional `pip` extras so a minimal install can run chat + memory only, and a NEW compiler-free path (`cpu` extra + SQLite/NumPy vector fallback) lets the whole stack install on a machine with no C++ toolchain.

## Languages

**Primary:**
- Python — entire backend, agent loop, services, tools, transports, and the install system. Sources rooted at `agent/` plus top-level packages (`transports/`, `discord_bot/`, `cursor-layla-mcp/`, `fabrication_assist/`). Ruff targets `py311` (`pyproject.toml` line 190).

**Secondary:**
- JavaScript / HTML / CSS — browser Web UI, no build step. Served static from `agent/ui/` (`agent/ui/index.html`, `agent/ui/js/*.js`, `agent/ui/css/layla.css`, vendored libs in `agent/ui/vendor/`).
- PowerShell — Windows-first installers and launchers. NEW canonical installers live at repo `install/`: `fresh_install.ps1` (compiler-free laptop install), `castilla.ps1`, `connect_tunnel.ps1`, plus `agent/install/install_service.ps1` / `uninstall_service.ps1`. Docs: `install/INSTALL.md`, `README-ES.md` (Spanish).

## Runtime

**Environment:**
- CPython **3.11 or 3.12 only**. `pyproject.toml` line 12: `requires-python = ">=3.11,<3.13"`. Line 11 warns 3.13+ is not validated against the Chroma/torch/sentence-transformers stack. `install/fresh_install.ps1` installs Python 3.12 via winget when missing. (Locally on this dev box only 3.14 is present, which is unsupported — verify changes statically; the app cannot run here.)
- ASGI server: **uvicorn** (`uvicorn[standard]>=0.32,<1`), launched from `agent/serve.py` / `agent/main.py`. Default port **8000**.

**Package Manager:**
- `pip` with PEP 621 optional-dependency extras (`pyproject.toml` `[project.optional-dependencies]`).
- Lockfile: `agent/requirements-lock.txt` present (pinned). Loose requirements at `agent/requirements.txt`; e2e extras at `agent/requirements-e2e.txt`. Separate small requirement sets for `discord_bot/requirements.txt` and `cursor-layla-mcp/requirements.txt`.
- `setuptools>=68` + `wheel` build backend (`pyproject.toml` lines 1-3). `fresh_install.ps1` installs `llama-cpp-python` and `torch` from prebuilt **CPU wheels** so no compiler is needed.

## Frameworks

**Core (extra `core`):**
- **FastAPI** `>=0.115,<1` — HTTP API and routing. Routers in `agent/routers/*.py` (`agent.py`, `autonomous.py`, `pairing.py`, `sync.py`, `system.py`, `openai_compat.py`, etc.).
- **Pydantic** `>=2.0` — request/response and config schemas (`agent/config_schema.py`, `agent/schemas/`).
- **uvicorn[standard]**, **python-multipart** — server + form/upload parsing.

**Compiler-free core (extra `cpu`, NEW):**
- Identical to `core` but **WITHOUT chromadb** (whose `chroma-hnswlib` is a C++ extension that won't build without a toolchain). Memory/RAG falls back to the SQLite+NumPy vector store (`agent/layla/memory/fallback_store.py`). This is what the laptop installer uses; add `chromadb` later for the native store. See `pyproject.toml` lines 62-91 and `install/fresh_install.ps1` (REQ-72).

**LLM inference (extra `llm`, optional):**
- **llama-cpp-python** `>=0.3.1,<0.4` — local GGUF inference (default backend).
- **litellm** `>=1.40.0` — multi-provider gateway / failover (`agent/services/litellm_gateway.py`).
- **instructor** `>=1.0,<2` — structured decision-JSON generation.

**Embeddings & RAG (extra `core`, integral to memory):**
- **sentence-transformers** `>=3.0,<4` + **torch**/**torchao** — embeddings (nomic-embed-text 768d, fallback all-MiniLM-L6-v2 384d; see `agent/layla/memory/vector_store.py`).
- **chromadb** `>=0.6.0,<1` — persistent vector store (`core` only; absent in `cpu`).
- **langchain-text-splitters**, **rank-bm25** (hybrid BM25 + vector retrieval), **tiktoken**, **torchao**.

**Testing:**
- **pytest** `>=8.0` with **pytest-asyncio** (`asyncio_mode = "auto"`), **pytest-timeout**, **pytest-cov**, **hypothesis** (extra `dev`). Config in `pyproject.toml` `[tool.pytest.ini_options]` + `agent/pytest.ini`; tests in `agent/tests/`.
- Markers: `slow`, `e2e_ui` (Playwright against live uvicorn). Browser e2e deps via `agent/requirements-e2e.txt`.

**Build/Dev:**
- **ruff** — lint + format (`[tool.ruff]`, line-length 120, rules `E,F,W,I`). Source roots `agent`, `fabrication_assist`.
- **bandit** (extra `security`) — security linting.
- The `dev` extra deliberately omits the GPU/model stack so tests import the app on a lightweight env (`pyproject.toml` lines 157-183, `docs/DEV_TESTING.md`).

## Install System (NEW, `agent/install/`)

- **`model_selector.py`** — loads `agent/models/model_catalog.json` and ranks models against probed hardware with a 0.9 RAM/VRAM safety margin. Public entry points: `recommend_model`, `recommend_kit` (line 184), `recommend_aspect_kit` (line 316), `recommend_language_assist` (line 322).
- **`hardware_probe.py`** — `probe_hardware()`; sizes context and GPU layers.
- **`provision_model.py`** + **`model_downloader.py`** — choose and fetch the best GGUF for the box, writing `runtime_config.json`. Downloader uses `huggingface_hub` when present, else resumable direct HTTP with atomic replace.
- Supporting: `installer_cli.py`, `setup_wizard.py`, `run_first_time.py`, `setup_existing_model.py`, `checks.py`, and capability `packs/` (`browser.json`, `voice.json`, `research.json`, `intelligence.json`, `observability.json`, `e2e.json`).

## Model Catalog (`agent/models/model_catalog.json`)

- ~42 entries. Categories (`_categories`): `general`, `coding`, `reasoning` (DeepSeek R1 family), `creative`, `fast` (<8GB VRAM), `flagship` (40GB+ VRAM). Coding tier centers on Qwen2.5-Coder 1.5B/3B/7B/14B/32B; general multilingual 1.5B/3B; plus reasoning and creative families. `ci-stub.gguf` is a tiny CI placeholder model.

## Key Dependencies

**Critical:**
- `fastapi`, `uvicorn`, `pydantic` — the server itself.
- `llama-cpp-python` — local inference engine (extra `llm`).
- `chromadb` + `sentence-transformers` — semantic memory; on `cpu`/no-toolchain installs `chromadb` is replaced by `fallback_store.py`.
- `apscheduler>=3.10,<4` — background schedulers (study, missions, consolidation).
- `networkx` — knowledge / reasoning graphs (`agent/layla/memory/knowledge_graph.graphml`).

**Infrastructure:**
- `httpx` / `requests` / `tenacity` — outbound HTTP + retries.
- `sqlite-utils` + stdlib `sqlite3` — relational store (`agent/layla/memory/db_connection.py`).
- `diskcache`, `orjson`, `psutil`, `numpy`, `keyring`, `PyYAML`, `unidiff`, `Pillow`.

**Optional capability extras (off unless installed):**
- `voice`: faster-whisper (STT), kokoro-onnx (TTS), soundfile.
- `vision`: easyocr.
- `crawl`: trafilatura, beautifulsoup4, playwright.
- `research`: pypdf, wikipedia, duckduckgo-search, arxiv, pandas, nbformat.
- `data`: duckdb, yfinance, scipy, scikit-learn, sympy, feedparser.
- `docs`: python-docx, openpyxl. `viz`: matplotlib. `nlp`: keybert, deep-translator.
- `tui`: textual. `network`: zeroconf (mDNS). `tray`: pystray. `watcher`: watchdog. `security`: bandit.
- `all` aggregates every capability extra (`pyproject.toml` lines 184-186); note `all` builds on `core` (with chromadb), not `cpu`.

## Configuration

**Environment:**
- `LAYLA_DATA_DIR` — relocates the SQLite DB, models dir, and data (`db_connection.py`). Defaults to repo root / `~/.layla`.
- `LAYLA_API_URL` / `LAYLA_BASE_URL` — point transports / MCP server at the API.
- Secrets read from config at call time, never logged (`agent/services/secret_filter.py`).

**Runtime config:**
- Single JSON file `agent/runtime_config.json` (template `agent/runtime_config.example.json`). Defaults/validation in `agent/runtime_safety.py`; `agent/first_run.py` auto-generates a hardware-tuned config. `agent/config_schema.py` + `agent/services/config_migrator.py` validate/migrate across versions.

**Build:**
- `pyproject.toml` (single source). Package discovery includes `fabrication_assist*`, `layla*`, `routers*`, `services*`, `capabilities*`, `install*`, `skills*` (lines 222-233).

## Platform Requirements

**Development:**
- Python 3.11/3.12. For tests, `pip install -e .[dev]` gives a no-GPU env; full capabilities need `.[all]` plus a GGUF model. Compiler-free path: `.[cpu,llm]`.
- Windows-first tooling (`.ps1` installers) but Linux/macOS supported.

**Production:**
- Local desktop / single-host. `Dockerfile` + `docker-compose.yml` provided (`docker_run` sandbox-escape flags blocked).
- GPU optional: `n_gpu_layers: -1` offloads all layers when a GPU is present; CPU-only and "potato preset" paths exist for low-end hardware (`docs/POTATO_MODE.md`).

---

*Stack analysis: 2026-06-30*
