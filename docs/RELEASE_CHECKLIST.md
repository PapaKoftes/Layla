# Release checklist — Layla

Run before tagging or publishing binaries/docs as “ready.” See also **`docs/PRODUCTION_CONTRACT.md`**.

## Automated

- [ ] **Tests**: from repo root, `cd agent && pytest tests/ -x -q` (full suite).
  - **CI** (`.github/workflows/ci.yml`) runs `pytest tests/ -m "not slow"` with a 60s per-test timeout — run **`not slow`** locally if you need CI parity; run **full** suite before release.
- [ ] **Lint**: `cd agent && ruff check .` (and any formatter the project uses).

## Manual smoke

- [ ] **Web UI**: start server (`START.bat` / `start.sh` or `uvicorn main:app` in `agent/`) → open `http://localhost:8000/ui`, send a message, confirm no silent blank errors.
- [ ] **CLI**: `python layla.py wakeup` (or equivalent) succeeds; `python layla.py pending` / `approve` if testing approval flow.
- [ ] **MCP** (if shipping Cursor MCP): smoke **`chat_with_layla`** or listed tools against a running server.
- [ ] **`GET /health`**: `status` ok or expected degraded; check **`effective_limits`**, **`model_routing`**, **`knowledge_index_*`**, **`cache_stats`**, **`response_cache_stats`**.

## Environment hygiene

- [ ] **Clean machine / fresh venv**: install via **`INSTALL.bat`** / **`install.sh`** (or `pip install -r agent/requirements.txt`) on a machine without prior Layla state; ensure **`runtime_config.json`** is created from **`runtime_config.example.json`** / first-run wizard.
- [ ] **Dependencies**: no missing imports on startup; optional extras documented in **`MODELS.md`** / **`docs/GETTING_THE_MODEL.md`** as needed.
- [ ] **No silent failures**: watch server logs for import errors during lifespan; verify tool **`INFO`** lines appear when tools run.

## Docs

- [ ] **`CHANGELOG.md`** updated.
- [ ] **`docs/PRODUCTION_CONTRACT.md`** still matches caps and `/health` fields if you changed defaults or observability.
