# Getting started with Layla

**Shortest path:** [ONBOARDING_15_MIN.md](ONBOARDING_15_MIN.md) (~15 minutes, one checklist).

## Quick Start (Windows — recommended)

1. Install **Python 3.11+** from [python.org](https://www.python.org/downloads/) and enable **Add Python to PATH**.
2. Clone this repository and double-click **`INSTALL.bat`** in the repo root (or run it from a terminal in that folder).
3. Follow the prompts: setup installs dependencies, offers **model selection** (auto, by category, or multiple GGUFs from the bundled catalog), validates **semantic memory (Chroma)**, then installs **Playwright Chromium** for browser tools.
4. The installer runs **`python scripts/run_layla.py`**, which starts the server and opens **http://127.0.0.1:8000/ui** (port may differ if set in `agent/runtime_config.json`).

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
