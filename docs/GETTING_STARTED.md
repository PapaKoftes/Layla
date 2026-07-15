# Getting started with Layla

**Shortest path:** [ONBOARDING_15_MIN.md](ONBOARDING_15_MIN.md) (~15 minutes, one checklist).

## Quick Start (Windows — recommended)

You do **not** need to install Python first — `INSTALL.bat` is powered by [uv](https://docs.astral.sh/uv/),
which fetches a standalone Python 3.12 and all prebuilt CPU wheels (no compiler, no admin).

1. Get the code: **Download ZIP** from the GitHub **Code** button and unzip it (or `git clone` if you have Git).
2. Double-click **`INSTALL.bat`** in the repo root (or run `.\INSTALL.bat` in a terminal there).
3. It creates `.venv`, installs dependencies from prebuilt wheels, **detects your hardware and downloads a fitting model**, writes `runtime_config.json`, and runs a **deep self-test** (a real inference turn — so a bad CPU wheel or too-large model is caught here, not on first chat).
4. When it finishes, start the app with **`.\layla.cmd`** — it opens **http://127.0.0.1:8000/ui** (port may differ if set in `agent/runtime_config.json`).

> Browser tools (Playwright Chromium) and heavier extras are **optional** and not part of the default install — add them only if you need them.

If anything fails, read the `[setup]` lines in the terminal — they report **model** status and **Semantic memory: ENABLED / DISABLED** (this line follows the in-process `LAYLA_CHROMA_DISABLED` flag and your `use_chroma` setting in `runtime_config.json`).

### Model downloads (partial files + resume)

When the installer downloads a **direct HTTP** `.gguf`, it writes to a `YourModel.gguf.part` file next to a small `YourModel.gguf.part.meta` sidecar. **Do not delete the `.part` or `.part.meta` file while a download is in progress** — re-running setup or the same download will **resume** with an HTTP `Range` request when the server supports it. The final `YourModel.gguf` appears only after the file passes a size/integrity check, then the partial is replaced atomically.

### Start the server before a large model finishes (optional)

1. Create `agent/.layla_pending_model.json` with: `{"name": "<exact name from model_catalog.json>"}`.
2. Start the app with `LAYLA_BACKGROUND_MODEL=1` or `python scripts/run_layla.py --background-model` (other flags as needed). The server comes up first; a background job downloads the catalog entry, updates **`model_filename`** in `runtime_config.json` via an atomic write, deletes the pending JSON, and writes **`agent/.layla_model_ready.flag`** (small JSON listing the basename) when the GGUF is ready. Poll **/setup_status** or **/health** until `pending_background_model` is false and the GGUF resolves.

## Advanced

- **Setup only (no server):** `python scripts/setup_layla.py`  
  Non-interactive / CI: `LAYLA_SETUP_NONINTERACTIVE=1` or `--yes` (auto model pick when no GGUF is present).
- **Run server after setup:** `python scripts/run_layla.py`
- **Desktop launcher:** `python scripts/build_launcher.py` builds **`Layla.exe`** (also copied to your Desktop on Windows). The launcher **does not embed the repo path**: it searches upward from the current working directory and the executable location for **`agent/main.py`** together with **`agent/runtime_safety.py`**, or uses **`LAYLA_REPO`** if the repo was moved.
- **Manual dev server:** activate `.venv`, `cd agent`, `uvicorn main:app --host 127.0.0.1 --port 8000`

Models are defined in **`agent/models/model_catalog.json`** (curated URLs only; no live scraping). See **[MODELS.md](../MODELS.md)** for hardware sizing context.

## Packaged Windows install

See `installer/build_installer.ps1` and `installer/layla.iss`. Data can live under `%LOCALAPPDATA%\Layla` via `LAYLA_DATA_DIR`.

## Remote access (phone)

- Enable `remote_enabled` and set `remote_api_key` in `runtime_config.json`.
- Optional: `POST /remote/tunnel/start` if `cloudflared` is on your PATH (HTTPS URL in `/remote/tunnel/status`).
- Set `remote_cors_origins` to your tunnel origin if the browser blocks API calls.

## Admin mode (trusted operator)

- `admin_mode: true` — skips approval prompts while keeping sandbox blocklists; optional git checkpoints via `admin_auto_checkpoint`.
- **Never** enable `admin_blocklist_override` unless you fully accept shell risk.

## Skill packs

Bundled manifests live under `skill_packs/`. Install more with `POST /skill_packs/install` `{ "url": "<git url>" }`.

---

## Quality enforcement (recommended)

For **coding-agent style** reliability (completion gate + deterministic tool routing), ensure your real `runtime_config.json` — not only the example file — contains at least:

```json
{
  "completion_gate_enabled": true,
  "deterministic_tool_routes_enabled": true
}
```

If these are omitted, older code paths default them off and enforcement is only partial. Copy from `agent/runtime_config.example.json` for the full template. Built-in `load_config()` defaults also enable both when the key is missing (see `agent/runtime_safety.py`), but an explicit `false` in your file still wins.

---

## Screenshots and demos for contributors

To refresh README visuals, see [media/README.md](media/README.md).
