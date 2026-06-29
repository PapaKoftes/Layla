---
last_mapped_commit: dc0b9c0ad8bdb1cba9afea771ad54a55473ec14d
---
# Technology Stack

**Analysis Date:** 2026-06-29

Layla is a local-first, multi-aspect AI companion / engineering agent. The runtime is a FastAPI HTTP server (`agent/main.py`, `agent/serve.py`) that drives an agentic tool-calling loop (`agent/agent_loop.py`) over a local GGUF model, with SQLite + ChromaDB as the memory substrate. Heavy ML dependencies are split into optional `pip` extras so a minimal install can run chat + memory only.

## Languages

**Primary:**
- Python — entire backend, agent loop, services, tools, transports. Sources rooted at `agent/` plus top-level packages (`transports/`, `discord_bot/`, `cursor-layla-mcp/`, `fabrication_assist/`). Ruff targets `py311` (`pyproject.toml` line 153).

**Secondary:**
- JavaScript / HTML / CSS — browser Web UI, no build step. Served static from `agent/ui/` (`agent/ui/index.html`, `agent/ui/js/*.js`, `agent/ui/css/layla.css`, vendored libs in `agent/ui/vendor/js/`).
- PowerShell / Batch / Bash — Windows-first installers and launchers (`install.ps1`, `INSTALL.bat`, `START.bat`, `install.sh`, `start.sh`, `agent/run-layla-server.ps1`).

## Runtime

**Environment:**
- CPython **3.11 or 3.12 only**. `pyproject.toml` line 12: `requires-python = ">=3.11,<3.13"`. Line 11 warns 3.13+ is not validated against the Chroma/torch/sentence-transformers stack. Several startup configs note 3.14 stability caveats (e.g. `embedder_prewarm_enabled` comment in `agent/runtime_config.example.json` line 327). The project's compiled bytecode in the tree is `cpython-314.pyc` — treat 3.12 as the supported cap regardless.
- ASGI server: **uvicorn** (`uvicorn[standard]>=0.32,<1`), launched from `agent/serve.py` / `agent/main.py`. Default port **8000** (`runtime_config` `port`).

**Package Manager:**
- `pip` with PEP 621 optional-dependency extras (`pyproject.toml` `[project.optional-dependencies]`).
- Lockfile: `agent/requirements-lock.txt` present (pinned). Loose requirements at `agent/requirements.txt`; e2e extras at `agent/requirements-e2e.txt`. Separate small requirement sets for `discord_bot/requirements.txt` and `cursor-layla-mcp/requirements.txt`.
- `setuptools>=68` + `wheel` build backend (`pyproject.toml` lines 1-3).

## Frameworks

**Core (extra `core`):**
- **FastAPI** `>=0.115,<1` — HTTP API and routing. Routers live in `agent/routers/*.py` (40+ routers: `agent.py`, `autonomous.py`, `pairing.py`, `sync.py`, `system.py`, `openai_compat.py`, etc.).
- **Pydantic** `>=2.0` — request/response and config schemas (`agent/config_schema.py`, `agent/schemas/`, `agent/decision_schema.py`).
- **uvicorn[standard]**, **python-multipart** — server + form/upload parsing.

**LLM inference (extra `llm`, optional):**
- **llama-cpp-python** `>=0.3.1,<0.4` — local GGUF inference (default backend).
- **litellm** `>=1.40.0` — multi-provider gateway / failover (`agent/services/litellm_gateway.py`).
- **instructor** `>=1.0,<2` — structured decision-JSON generation (`use_instructor_for_decisions`).

**Embeddings & RAG (extra `core`, integral to memory):**
- **sentence-transformers** `>=3.0,<4` — embeddings (nomic-embed-text 768d, fallback all-MiniLM-L6-v2 384d; see `agent/layla/memory/vector_store.py`).
- **chromadb** `>=0.6.0,<1` — sole persistent vector store (FAISS removed; `vector_store.py`).
- **langchain-text-splitters**, **rank-bm25** (hybrid BM25 + vector retrieval), **tiktoken**, **torchao**.

**Testing:**
- **pytest** `>=8.0` with **pytest-asyncio** (`asyncio_mode = "auto"`), **pytest-timeout**, **pytest-cov**, **hypothesis** (extra `dev`). Config in `pyproject.toml` `[tool.pytest.ini_options]` + `agent/pytest.ini`; tests in `agent/tests/`.
- Markers: `slow`, `e2e_ui` (Playwright against live uvicorn). Browser e2e deps via `agent/requirements-e2e.txt`.

**Build/Dev:**
- **ruff** — lint + format (`[tool.ruff]`, line-length 120, rules `E,F,W,I`). Source roots `agent`, `fabrication_assist`.
- **bandit** (extra `security`) — security linting.
- The `dev` extra deliberately omits the GPU/model stack (no llama-cpp-python, torch, chromadb, sentence-transformers) so tests import the app on a lightweight 3.12 env (see `pyproject.toml` lines 115-146 and `docs/DEV_TESTING.md`).

## Key Dependencies

**Critical:**
- `fastapi`, `uvicorn`, `pydantic` — the server itself.
- `llama-cpp-python` — local inference engine (extra `llm`).
- `chromadb` + `sentence-transformers` — semantic memory; without them retrieval degrades (`use_chroma: false` path for weak hardware).
- `apscheduler>=3.10,<4` — background schedulers (study, missions, consolidation; `scheduler_*` config keys).
- `networkx` — knowledge / reasoning graphs (`agent/services/graph_*.py`, `knowledge_graph.graphml`).

**Infrastructure:**
- `httpx` / `requests` / `tenacity` — outbound HTTP + retries.
- `sqlite-utils` + stdlib `sqlite3` — relational store (`agent/layla/memory/db_connection.py`).
- `diskcache`, `orjson`, `psutil`, `numpy`, `PyYAML`, `unidiff`, `Pillow`.

**Optional capability extras (off unless installed):**
- `voice`: faster-whisper (STT), kokoro-onnx (TTS), soundfile.
- `vision`: easyocr.
- `crawl`: trafilatura, beautifulsoup4, playwright.
- `research`: pypdf, wikipedia, duckduckgo-search, arxiv, pandas, nbformat.
- `data`: duckdb, yfinance, scipy, scikit-learn, sympy, feedparser.
- `docs`: python-docx, openpyxl. `viz`: matplotlib. `nlp`: keybert, deep-translator.
- `tui`: textual (`agent/tui.py`). `network`: zeroconf (mDNS discovery).
- `all` aggregates every capability extra (`pyproject.toml` lines 147-149).

## Configuration

**Environment:**
- `LAYLA_DATA_DIR` — relocates the SQLite DB, models dir, and data (`db_connection.py` line 18). Defaults to the repo root / `~/.layla`.
- `LAYLA_API_URL` / `LAYLA_BASE_URL` — point transports / MCP server at the API (`transports/base.py`, `cursor-layla-mcp/server.py`).
- Secrets are read from config at call time, never logged (`agent/services/secret_filter.py`).

**Runtime config:**
- Single JSON file `agent/runtime_config.json` (template `agent/runtime_config.example.json`, ~560 keys). Defaults and validation live in `agent/runtime_safety.py`. `agent/first_run.py` auto-generates a hardware-tuned config; `agent/probe_hardware.py` / `agent/services/hardware_detect.py` size context and GPU layers.
- `agent/config_schema.py` + `agent/services/config_migrator.py` validate / migrate config across versions.

**Build:**
- `pyproject.toml` (single source). Package discovery includes `fabrication_assist*`, `layla*`, `routers*`, `services*`, `capabilities*`, `skills*` (lines 185-196).

## Platform Requirements

**Development:**
- Python 3.11/3.12. For tests, `pip install -e .[dev]` gives a no-GPU env; full capabilities need `.[all]` plus a GGUF model.
- Windows-first tooling (`.bat` / `.ps1` launchers) but Linux/macOS supported (`install.sh`, POSIX rlimit/cgroup worker controls in config).

**Production:**
- Local desktop / single-host. `Dockerfile` + `docker-compose.yml` provided (note: `docker_run` sandbox-escape flags are blocked per recent security work).
- GPU optional: `n_gpu_layers: -1` offloads all layers when a GPU is present; CPU-only and "potato preset" paths exist for low-end hardware (`docs/POTATO_MODE.md`).

---

*Stack analysis: 2026-06-29*
