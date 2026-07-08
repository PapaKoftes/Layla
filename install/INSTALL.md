# Layla — Fresh Install & Connect

A clean, **compiler-free** setup for a new Windows machine, with a deep self-test that
proves it actually works, plus a guided wizard to pair two Layla installs.

## 1. Install (one command)

```powershell
git clone https://github.com/PapaKoftes/Layla.git
cd Layla
powershell -ExecutionPolicy Bypass -File install\fresh_install.ps1
```

What it does (no C++ toolchain required):
1. Selects **Python 3.12** (installs it via winget if missing) — never the system 3.14.
2. Creates `.venv`.
3. Installs **llama-cpp-python** + **torch** from prebuilt **CPU wheels**.
4. Installs Layla's `[cpu,llm]` extras — compiler-free (no `chromadb`; memory uses the
   SQLite+NumPy fallback automatically, so RAG still works).
5. **Detects the hardware** and downloads the **best coding kit** for it, writing
   `runtime_config.json`.
6. **Deep self-test** (`scripts/selftest.py`): resolves the model, validates the GGUF, and
   **runs one real inference turn in a subprocess** — so an AVX-512 `SIGILL` from a bad CPU
   wheel, an out-of-memory model, or a corrupt download is caught *here*, not on first use.
   On failure it auto-reinstalls the llama-cpp wheel and retries, or exits with the exact cause.

Options: `-Prefer quality|balanced|lite|speed`, `-SkipModel`, `-Spanish`, `-LanguageHelper`,
`-Aspects "morrigan,nyx"`, `-Verify` (re-run the self-test only), `-Pair` (launch pairing).

### Start it
```powershell
.\.venv\Scripts\Activate.ps1
cd agent
python serve.py            # then open http://127.0.0.1:8000/ui
```

### Re-check health any time
```powershell
powershell -ExecutionPolicy Bypass -File install\fresh_install.ps1 -Verify
```
This boots the server and checks `/health`, a real `/agent` turn, and `/ui` end-to-end.

> On a **16 GB CPU** machine the provisioner picks **Qwen2.5-Coder-3B** (the "morrigan"
> coding aspect) by default — verified to load and complete a turn on exactly that tier.
> Use `-Prefer quality` for a larger model if you have the RAM, or `-Prefer lite`/`speed` for
> a smaller, faster one.

## 2. Pair two Layla installs (main PC ↔ laptop)

The easiest path is the **guided wizard** — run it on each machine:

```powershell
.\.venv\Scripts\python.exe scripts\pair.py
```

- On the machine that hosts the model, choose **HOST**: it enables remote access, rotates a
  one-time **bearer token** (stored only as a hash — `tunnel_token_hash`, never plaintext),
  and prints the **address + token** (LAN address, or a Cloudflare tunnel URL for over-the-internet).
- On the other machine, choose **CLIENT**: paste the address + token. The wizard makes an
  **authenticated request and verifies the link round-trips** before saving the peer — so you
  know immediately whether it worked.

Security is on by default: when exposed, remote auth is **required** (REQ-11), and the client
IP comes from Cloudflare's unforgeable `Cf-Connecting-Ip` (REQ-10), so a spoofed
`X-Forwarded-For` can't bypass the allowlist.

Prefer the manual tunnel? `install\connect_tunnel.ps1` does the host side (installs
`cloudflared`, enables remote, stores a hashed token, opens the HTTPS URL). Same home network?
Skip the tunnel and use the LAN address the wizard prints.

## 3. Organize Layla on the main PC

- A clean runtime lives in `.venv` (the one command above). `.venv-test` is for the test suite.
- Models live in `models/` (gitignored); `provision_model.py` is idempotent and won't
  re-download an existing GGUF.
- Secrets (`tunnel_token_hash`, provider keys) go in the **OS keyring** when set via the UI
  (REQ-12); `runtime_config.json` holds non-secret config.
- Before sharing a build: `python scripts/check_copyleft.py` and the test suite (`pytest` in `agent/`).

## Troubleshooting
- **No Python 3.12**: install from https://python.org ("Add to PATH"), re-run.
- **Self-test fails on the inference turn (SIGILL / illegal instruction)**: the llama-cpp CPU
  wheel uses instructions this CPU lacks. The installer auto-retries a reinstall; if it persists,
  the machine is very old — try `-Prefer lite`.
- **chromadb errors**: you don't need it — `[cpu]` omits it and memory falls back automatically.
- **Slow generation**: expected on CPU. Use `-Prefer lite`/`speed`, or run the model on the main
  PC and connect the laptop to it via the pairing wizard.
- **Use the supported installer**: the root `install.ps1` / `INSTALL.bat` (or `install.sh` on
  Unix) now forward to `install\bootstrap.ps1`, the compiler-free uv installer — no build
  toolchain required. `install\fresh_install.ps1` remains available for a from-scratch reinstall.
```

