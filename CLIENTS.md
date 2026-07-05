# Layla clients

Layla runs a local server (default `http://127.0.0.1:8000`) that speaks the OpenAI and
Ollama APIs, so you can reach it from a terminal, your phone, or your editor — no cloud.

## Terminal (CLI)

Dependency-free, ships in the repo:

```bash
python -m clients.layla_cli "what changed in this repo?"   # one-shot
python -m clients.layla_cli                                # interactive REPL
python -m clients.layla_cli --model layla-nyx --no-stream "explain asyncio"
```

Flags: `--base-url`, `--model` (`layla` or `layla-<aspect>`), `--no-stream`, `--timeout`.
REPL commands: `/reset`, `/quit`.

## Mobile / desktop (PWA)

The web UI is an installable Progressive Web App — `ui/manifest.json` + a registered
service worker (`ui/sw.js`). Open `http://<host>:8000/ui` on a phone and "Add to Home
Screen"; it launches standalone. Reach it from another device via the remote-access
tunnel (the `remote` feature) or your LAN IP.

## Editors (VS Code / JetBrains / CLI coding agents)

Any tool that speaks the OpenAI or Ollama API can point at Layla — no plugin needed,
because Layla *serves* both (`/v1/chat/completions` and `/api/chat`). Standard sampling
params (`temperature`, `max_tokens`, `top_p`, `stop`, `seed`) are honoured.

**Continue** (`~/.continue/config.json`):
```json
{ "models": [{ "title": "Layla", "provider": "openai",
  "model": "layla", "apiBase": "http://127.0.0.1:8000/v1", "apiKey": "none" }] }
```

**Cline / Aider** — select the "OpenAI-compatible" provider, base URL
`http://127.0.0.1:8000/v1`, model `layla`.

**Ollama clients** (Open WebUI, ollama-python) — point at `http://127.0.0.1:8000`; Layla
answers `/api/tags`, `/api/chat`, `/api/generate`, `/api/version`.

## Desktop shell (Tauri)

A native window wrapping the local UI — see the Tauri scaffold under `desktop/` (BL-154).
