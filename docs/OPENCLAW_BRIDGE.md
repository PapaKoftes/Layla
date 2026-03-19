# OpenClaw ↔ Layla bridge (HTTP sidecar)

OpenClaw runs a **Node** gateway with many channels. Layla is a **Python** FastAPI app with `POST /agent`. You do **not** need to merge codebases: run them side-by-side and forward channel text to Layla.

## Topology

```text
(Channel) → OpenClaw Gateway → HTTP POST → Layla :8000/agent → response text → Gateway → Channel
```

Layla stays the authority for tools, approvals, and local GGUF. The gateway is a **thin forwarder** (or a small script) that maps channel identity to JSON fields.

## Request shape

`POST http://127.0.0.1:8000/agent` with JSON (minimal):

```json
{
  "message": "User text here",
  "context": "",
  "workspace_root": "C:\\\\path\\\\to\\\\repo",
  "allow_write": false,
  "allow_run": false,
  "aspect_id": "morrigan"
}
```

Use `allow_write` / `allow_run` only if your operator policy allows it; Layla still enforces approvals for dangerous tools.

## Environment

- **`LAYLA_API_URL`** (env) or **`layla_api_url`** in `runtime_config.json` — base URL for Layla (see `transports/base.py`). Point your forwarder at the same value.

## Security

- **Bind Layla to localhost** (`127.0.0.1`) unless you have TLS + auth.
- **Optional shared secret:** if you add a reverse proxy or custom middleware later, prefer a header check; today `/agent` follows `runtime_config.json` (`anonymous_access`, remote API key, etc.) — see `docs/REMOTE_ARCHITECTURE.md`.
- **Channel trust:** mirror Layla’s transport policy — [OPENCLAW_ALIGNMENT.md](OPENCLAW_ALIGNMENT.md) and [transports/README.md](../transports/README.md) (allowlist + `/pair`).

## Diagnostics

If the gateway exposes HTTP (e.g. health on `/health`), set in `runtime_config.json`:

```json
"openclaw_gateway_url": "http://127.0.0.1:18789"
```

`layla.py doctor` / `GET /doctor` will attempt `GET {url}/health` when this key is set (path-only URLs use `/health` automatically).

## MCP vs HTTP

Cursor uses `cursor-layla-mcp/server.py` (MCP). For a multi-channel gateway, **raw HTTP to `/agent`** is simpler than embedding MCP.
