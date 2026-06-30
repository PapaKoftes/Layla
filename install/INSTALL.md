# Layla — Fresh Install & Connect

A clean, **compiler-free** setup for a new Windows laptop, plus connecting it to your
main-PC Layla over a secure tunnel.

## 1. Install on the laptop (one command)

```powershell
git clone https://github.com/PapaKoftes/Layla.git
cd Layla
powershell -ExecutionPolicy Bypass -File install\fresh_install.ps1
```

What it does (no C++ toolchain required):
1. Installs **Python 3.12** (via winget) if missing.
2. Creates `.venv`.
3. Installs **llama-cpp-python** and **torch** from prebuilt **CPU wheels**.
4. Installs Layla's `[cpu,llm]` extras — the compiler-free set (no `chromadb`; memory
   uses the SQLite+NumPy fallback automatically).
5. **Detects the hardware** and downloads the **best coding kit** for it
   (`agent/install/provision_model.py` → `recommend_kit`), writing `runtime_config.json`.

Options: `-Prefer quality|balanced|speed`, `-SkipModel`.

### Start it
```powershell
.\.venv\Scripts\Activate.ps1
cd agent
python serve.py            # open http://127.0.0.1:8000
```

On a 16GB CPU laptop the provisioner picks **Qwen2.5-Coder-7B** (the "morrigan"/architect
coding aspect), ~5 tok/s, 100% on the bundled benchmark. Use `-Prefer speed` for a smaller,
faster model.

## 2. Connect the laptop to your main-PC Layla (remote tunnel)

Run Layla on the **main PC** (it has the model), expose it with a tunnel, and point the
laptop at it. Security is on by default: remote auth is **required** when exposed (REQ-11),
and the client IP comes from Cloudflare's unforgeable `Cf-Connecting-Ip` (REQ-10) — a
spoofed `X-Forwarded-For` cannot bypass auth/allowlist.

**Main PC (host):**
```powershell
# terminal 1
cd agent ; python serve.py
# terminal 2
powershell -ExecutionPolicy Bypass -File install\connect_tunnel.ps1
```
It installs `cloudflared`, sets `remote_enabled=true`, ensures a **bearer token**, prints the
token, and opens a public HTTPS URL.

**Laptop (client):** in Settings (or `runtime_config.json`) point the remote host at the
printed URL and send `Authorization: Bearer <token>`. To use the main PC purely as the model
backend, set `llama_server_url` to the tunnel URL.

> Same home network instead? Skip the tunnel and use Layla's built-in LAN pairing
> (zeroconf) — both instances discover each other directly.

## 3. Organize Layla on the main PC

- Move from the dev `.venv-test` to a clean `.venv` with the same one command above
  (or keep `.venv-test` for running the test suite).
- Models live in `agent/models/` (gitignored). Keep the GGUFs there; `provision_model.py`
  is idempotent and won't re-download an existing model.
- Secrets (`remote_api_key`, provider keys) are stored in the **OS keyring** when set via
  the UI (REQ-12); `runtime_config.json` holds non-secret config.
- Run `python scripts/check_copyleft.py` and the test suite (`pytest` in `agent/`) before
  sharing a build.

## Troubleshooting
- **No Python 3.12**: install from https://python.org (check "Add to PATH"), re-run.
- **chromadb errors**: you don't need it — the `[cpu]` extra omits it and memory falls back
  automatically. Only install `chromadb` if you specifically want the native vector store
  (needs a C++ build toolchain).
- **Slow generation**: expected on CPU (~5 tok/s for 7B). Use `-Prefer speed`, or run the
  model on the main PC and connect over the tunnel.
