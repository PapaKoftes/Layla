# Release checklist — Layla

Run before tagging or publishing binaries/docs as “ready.” See also **`docs/PRODUCTION_CONTRACT.md`**.

## Release verification (1.2.0 — 2026-04-14)

| Step | Verified |
|------|----------|
| Full test suite: `cd agent && pytest tests/ -x -q` | Yes (run before tag) |
| CI parity: `pytest tests/ -m "not slow and not e2e_ui and not browser_smoke and not voice_smoke and not gpu_smoke"` per **`docs/VERIFICATION.md`** | Yes |
| Lint: `cd agent && ruff check .` | Yes (run before tag) |
| Web UI smoke: server → `http://localhost:8000/ui` → send message | Manual |
| Optional: [GOLDEN_FLOW.md](GOLDEN_FLOW.md) **§10** ten-minute operator acceptance | Manual |
| CLI: `python layla.py wakeup` | Manual |
| MCP smoke (if shipping): `chat_with_layla` against running server | Manual |
| `GET /health`: status, `effective_limits`, `model_routing`, knowledge index fields | Manual |
| Fresh venv: **`INSTALL.bat`** / **`install.sh`** → **`runtime_config.json`** / wizard | Manual |
| Windows packaged install (VM): numbered gate below | Manual ([`installer/README.md`](../installer/README.md)) |
| No startup import errors; tool runs log at INFO | Manual |
| **`CHANGELOG.md`** version matches **`agent/version.py`** | Yes for1.2.0 |
| **`docs/PRODUCTION_CONTRACT.md`** still matches `/health` if defaults changed | Review |

**Sign-off:** Tag **`v1.2.0`** after the rows above are satisfied for your environment.  
**Python:** Supported runtimes are **3.11–3.12**. `agent/main.py` exits on **3.13+** unless **`LAYLA_ALLOW_UNSUPPORTED_PYTHON=1`** (unsupported). Tests set this automatically in **`agent/conftest.py`** when needed.

### Windows packaged installer (clean VM) — numbered gate

1. On a maintainer machine with **Python 3.11/3.12** (`py -3.12` recommended), build the payload/installer per [`installer/README.md`](../installer/README.md) (`build_installer.ps1`, Inno Setup when `iscc` is available).
2. On a **fresh Windows VM or clean user profile**, run the produced `Layla-Setup-*.exe` (from `installer/output/` when built).
3. Launch Layla from the Start Menu or shortcut; confirm `%LOCALAPPDATA%\Layla` exists and `runtime_config.json` is seeded from the example template when missing.
4. Complete first-run / model selection; place or download a **small GGUF**; confirm `GET http://127.0.0.1:8000/health` returns **200** and `GET http://127.0.0.1:8000/ui` loads.
5. Send **one chat turn** in `/ui` (no silent failure).
6. Optional: `GET /doctor/capabilities?browser_launch=true` on the installed build; optional voice micro probe with `voice_micro=true` (slow).

Record evidence (screenshot or short log) in release notes when publishing binaries.

## Automated (reference)

- **Tests**: from repo root, `cd agent && pytest tests/ -x -q` (full suite).
  - **CI** (`.github/workflows/ci.yml`) runs `pytest tests/ -m "not slow and not e2e_ui and not browser_smoke and not voice_smoke and not gpu_smoke"` with coverage (`pytest-cov`, floor in `agent/.coveragerc`) and a 60s per-test timeout on **Ubuntu**; a **Windows** job runs the same pytest marker set without the coverage floor — see **[VERIFICATION.md](VERIFICATION.md)** for the exact CI-parity command; run **full** suite before release.
  - **Deep** (`.github/workflows/verify-deep.yml`): scheduled + manual — UI e2e, browser smoke, voice smoke, doctor JSON artifact.
- **Lint**: `cd agent && ruff check .` (and any formatter the project uses).

## Manual smoke (reference)

- **Web UI**: start server (`START.bat` / `start.sh` or `uvicorn main:app` in `agent/`) → open `http://localhost:8000/ui`, send a message, confirm no silent blank errors.
- **CLI**: `python layla.py wakeup` (or equivalent) succeeds; `python layla.py pending` / `approve` if testing approval flow.
- **MCP** (if shipping Cursor MCP): smoke **`chat_with_layla`** or listed tools against a running server.
- **`GET /health`**: `status` ok or expected degraded; check **`effective_limits`**, **`model_routing`**, **`knowledge_index_*`**, **`cache_stats`**, **`response_cache_stats`**.

## Environment hygiene (reference)

- **Clean machine / fresh venv**: install via **`INSTALL.bat`** / **`install.sh`** (or `pip install -r agent/requirements.txt`) on a machine without prior Layla state; ensure **`runtime_config.json`** is created from **`runtime_config.example.json`** / first-run wizard.
- **Dependencies**: no missing imports on startup; optional extras documented in **`MODELS.md`** / **`docs/GETTING_THE_MODEL.md`** as needed.
- **No silent failures**: watch server logs for import errors during lifespan; verify tool **`INFO`** lines appear when tools run.

## Docs (reference)

- **`CHANGELOG.md`** updated.
- **`docs/PRODUCTION_CONTRACT.md`** still matches caps and `/health` fields if you changed defaults or observability.
