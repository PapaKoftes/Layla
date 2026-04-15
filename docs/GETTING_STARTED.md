# Getting started with Layla

## Quick path (developers)

1. Install Python **3.11 or 3.12** (recommended).
2. Run `INSTALL.bat` (Windows) or `./install.sh` (Linux/macOS).
3. Start with `START.bat` / `./start.sh` or `uvicorn main:app` from the `agent/` folder.
4. Open **http://127.0.0.1:8000/ui** and complete the setup overlay (model + workspace).

## Packaged Windows install

See `installer/build_installer.ps1` and `installer/layla.iss`. Data lives under `%LOCALAPPDATA%\Layla` via `LAYLA_DATA_DIR`.

## Remote access (phone)

- Enable `remote_enabled` and set `remote_api_key` in `runtime_config.json`.
- Optional: `POST /remote/tunnel/start` if `cloudflared` is on your PATH (HTTPS URL in `/remote/tunnel/status`).
- Set `remote_cors_origins` to your tunnel origin if the browser blocks API calls.

## Admin mode (trusted operator)

- `admin_mode: true` — skips approval prompts while keeping sandbox blocklists; optional git checkpoints via `admin_auto_checkpoint`.
- **Never** enable `admin_blocklist_override` unless you fully accept shell risk.

## Skill packs

Bundled manifests live under `skill_packs/`. Install more with `POST /skill_packs/install` `{ "url": "<git url>" }`.
