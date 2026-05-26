# Remote Access Setup Guide

Layla can be reached from outside your local machine through either a **Cloudflare Quick Tunnel** or a **Tailscale mesh VPN**. Both options wrap the local server at `http://127.0.0.1:8000` and expose it over HTTPS with token-based authentication.

---

## Table of Contents

1. [Prerequisites](#1-prerequisites)
2. [Quick Tunnel Setup with Cloudflared](#2-quick-tunnel-setup-with-cloudflared)
3. [Token-Based Authentication](#3-token-based-authentication)
4. [Rotating Tokens](#4-rotating-tokens)
5. [IP Allowlist](#5-ip-allowlist)
6. [Audit Logging](#6-audit-logging)
7. [Tailscale Alternative](#7-tailscale-alternative)
8. [Health Monitoring and Auto-Restart](#8-health-monitoring-and-auto-restart)
9. [Security Best Practices](#9-security-best-practices)
10. [Troubleshooting](#10-troubleshooting)

---

## 1. Prerequisites

You need **one** of the following installed and on your PATH:

### Option A: Cloudflared (recommended for quick, zero-config access)

Download from https://developers.cloudflare.com/cloudflare-one/connections/connect-apps/install-and-setup/installation/

Verify installation:
```bash
cloudflared --version
```

If the binary is not on PATH, set `cloudflared_path` in `runtime_config.json` to the full path.

### Option B: Tailscale (recommended for persistent private networks)

Download from https://tailscale.com/download

Verify installation:
```bash
tailscale --version
```

### Common requirements

- Layla server running locally on the configured port (default 8000)
- `remote_enabled` set to `true` in `runtime_config.json`

---

## 2. Quick Tunnel Setup with Cloudflared

Cloudflared creates a temporary public `*.trycloudflare.com` URL that proxies traffic to your local Layla instance. No Cloudflare account needed.

### Step 1: Enable remote mode

In `agent/runtime_config.json`:
```json
{
  "remote_enabled": true,
  "port": 8000
}
```

### Step 2: Start the tunnel

**Via API** (from localhost):
```bash
curl -X POST http://127.0.0.1:8000/remote/tunnel/start
```

Response:
```json
{
  "ok": true,
  "running": true,
  "message": "started; URL will appear in /remote/tunnel/status when ready"
}
```

### Step 3: Get the tunnel URL

The `*.trycloudflare.com` URL takes a few seconds to appear. Poll for it:
```bash
curl http://127.0.0.1:8000/remote/tunnel/status
```

Response:
```json
{
  "running": true,
  "url": "https://some-random-words.trycloudflare.com"
}
```

Use that URL from any device. All requests to it require a valid Bearer token (see section 3).

### Step 4: Stop the tunnel

```bash
curl -X POST http://127.0.0.1:8000/remote/tunnel/stop
```

---

## 3. Token-Based Authentication

All non-localhost requests must include a Bearer token in the `Authorization` header. Tokens are **never stored in plaintext** -- only their SHA-256 hash is persisted in the config.

### How it works

1. A token is generated via the `/remote/token/rotate` endpoint.
2. The SHA-256 hash is saved as `tunnel_token_hash` in `runtime_config.json`.
3. The plaintext token is shown to you **once** -- save it immediately.
4. Every remote request is validated by hashing the presented token and comparing it (constant-time via `hmac.compare_digest`) against the stored hash.

### Using the token

Include it as a Bearer token in every remote request:
```bash
curl -H "Authorization: Bearer YOUR_TOKEN_HERE" \
  https://your-tunnel-url.trycloudflare.com/agent
```

### Authentication flow (middleware)

For every non-localhost request, the middleware checks in order:
1. **IP allowlist** -- is the client IP permitted?
2. **Token expiry** -- has the token exceeded its TTL?
3. **Token validation** -- does the hash match?
4. **Endpoint allowlist** -- is the requested path in the allowed set?

If any check fails, the request is denied with 401 or 403.

### Legacy support

The old `remote_api_key` (plaintext) still works as a fallback but logs a deprecation warning. Migrate to hashed tokens as soon as possible.

---

## 4. Rotating Tokens

Rotate tokens regularly. Each rotation generates a new cryptographically secure 256-bit token (`secrets.token_urlsafe(32)`).

### Rotate via API

```bash
curl -X POST http://127.0.0.1:8000/remote/token/rotate
```

Response:
```json
{
  "ok": true,
  "token": "aB3x...long-random-string...",
  "message": "Save this token — it will not be shown again."
}
```

**Save the `token` value immediately.** It cannot be recovered -- only the hash is stored.

### What happens on rotation

The endpoint writes two keys to `runtime_config.json`:
- `tunnel_token_hash` -- SHA-256 hex digest of the new token
- `tunnel_token_created_at` -- ISO-8601 UTC timestamp

The previous token is invalidated immediately.

### Token expiry (TTL)

Set `tunnel_token_ttl_hours` in `runtime_config.json` to auto-expire tokens:

```json
{
  "tunnel_token_ttl_hours": 24
}
```

- `0` (default) = token never expires
- Any positive value = hours until the token is considered expired

When a token expires, all remote requests are denied until you rotate again.

---

## 5. IP Allowlist

Restrict remote access to specific IP addresses or CIDR ranges.

### Configuration

In `runtime_config.json`:
```json
{
  "tunnel_ip_allowlist": [
    "203.0.113.50",
    "10.0.0.0/8",
    "192.168.1.0/24"
  ]
}
```

### Rules

- **Empty list (default):** all IPs are allowed (authentication still required).
- **Non-empty list:** only listed IPs/CIDRs can connect.
- **Localhost is always allowed** regardless of the allowlist (`127.0.0.1`, `::1`, `::ffff:127.0.0.1`).
- Both IPv4 and IPv6 addresses are supported.
- Invalid entries in the list are skipped with a warning in the log.

### Example: allow only your office and home

```json
{
  "tunnel_ip_allowlist": [
    "198.51.100.10",
    "203.0.113.0/24"
  ]
}
```

---

## 6. Audit Logging

Every tunnel access attempt (allowed or denied) is recorded in a SQLite database for compliance and abuse detection.

### Enable auditing

In `runtime_config.json`:
```json
{
  "tunnel_audit_enabled": true
}
```

### Database location

```
~/.layla/tunnel_audit.db
```

Table: `tunnel_access_log`

Each row contains:
| Column | Description |
|--------|-------------|
| `timestamp` | ISO-8601 UTC |
| `client_ip` | Requesting IP |
| `path` | URL path |
| `method` | HTTP method |
| `token_id` | First 8 chars of the token's SHA-256 hash |
| `result` | `"allow"` or `"deny"` |
| `detail` | Denial reason (if any) |

### Query the audit log

```bash
# Last 7 days, up to 100 entries
curl http://127.0.0.1:8000/remote/audit

# Filter by result, custom range
curl "http://127.0.0.1:8000/remote/audit?days=30&limit=500&result=deny"
```

### Get aggregate summary

```bash
curl http://127.0.0.1:8000/remote/audit/summary
```

Response:
```json
{
  "ok": true,
  "total_requests": 342,
  "allowed": 310,
  "denied": 32,
  "unique_ips": 5,
  "top_paths": [["/agent", 200], ["/remote/tunnel/status", 80]],
  "top_ips": [["203.0.113.50", 150], ["10.0.1.5", 100]]
}
```

### Purge old entries

Old entries can be purged programmatically via `tunnel_audit.purge_old(days=90)`. This deletes all records older than the specified number of days (default 90).

---

## 7. Tailscale Alternative

Tailscale creates a private mesh VPN. Only devices signed into your tailnet can reach each other -- no public URLs, no tokens exposed to the internet.

### Start Tailscale

```bash
curl -X POST http://127.0.0.1:8000/remote/tailscale/start
```

If you need headless (unattended) auth, set `tailscale_auth_key` in `runtime_config.json`:
```json
{
  "tailscale_auth_key": "tskey-auth-..."
}
```

### Check status

```bash
curl http://127.0.0.1:8000/remote/tailscale/status
```

Response:
```json
{
  "running": true,
  "ip": "100.64.1.5",
  "hostname": "my-machine",
  "backend_state": "Running",
  "tailnet": "example.ts.net"
}
```

Access Layla from any device on the same tailnet:
```
http://100.64.1.5:8000
```
Or using MagicDNS:
```
http://my-machine:8000
```

### Tailscale Funnel (public HTTPS)

To expose Layla publicly via Tailscale's HTTPS funnel:

```bash
# Start funnel
curl -X POST http://127.0.0.1:8000/remote/tailscale/funnel/start

# Stop funnel
curl -X POST http://127.0.0.1:8000/remote/tailscale/funnel/stop
```

The public URL follows the pattern `https://<hostname>.<tailnet>`.

### Stop Tailscale

```bash
curl -X POST http://127.0.0.1:8000/remote/tailscale/stop
```

---

## 8. Health Monitoring and Auto-Restart

The tunnel manager tracks consecutive health-check failures and can automatically restart the tunnel.

### Manual health check

```bash
curl http://127.0.0.1:8000/remote/tunnel/health
```

Response when healthy:
```json
{
  "ok": true,
  "healthy": true,
  "url": "https://some-random-words.trycloudflare.com",
  "status_code": 200
}
```

Response when unhealthy:
```json
{
  "ok": true,
  "healthy": false,
  "url": "https://some-random-words.trycloudflare.com",
  "reason": "HTTP Error 502: Bad Gateway"
}
```

### Auto-restart logic

The `auto_restart_if_unhealthy()` function (in `tunnel_manager.py`) works as follows:

1. Sends a HEAD request to the active tunnel URL.
2. Tracks consecutive failures in an internal counter.
3. After **3 consecutive failures** (configurable via `max_failures` parameter), the tunnel is automatically stopped and restarted.
4. The failure counter resets to 0 on any successful health check or after a restart.

### Health state inspection

The internal health state can be read programmatically:
```python
from services.tunnel_manager import get_health_state
state = get_health_state()
# {
#   "consecutive_failures": 1,
#   "max_failures_before_restart": 3,
#   "last_health_check": 1716000000.0,
#   "last_local_url": "http://127.0.0.1:8000"
# }
```

---

## 9. Security Best Practices

1. **Always rotate tokens after first setup.** Run `POST /remote/token/rotate` immediately. The initial config has no token set.

2. **Set a token TTL.** Use `tunnel_token_ttl_hours` (e.g. 24 or 72) to force regular rotation. Expired tokens are rejected automatically.

3. **Use the IP allowlist.** If you know which IPs will connect, lock it down with `tunnel_ip_allowlist`.

4. **Enable audit logging.** Set `tunnel_audit_enabled: true` and review the audit summary periodically for unexpected IPs or high denial rates.

5. **Migrate off `remote_api_key`.** The legacy plaintext key is deprecated. Use hashed tokens (`tunnel_token_hash`) exclusively.

6. **Prefer Tailscale for persistent access.** Tailscale's mesh VPN avoids exposing a public URL entirely. Traffic stays within your private tailnet and is encrypted end-to-end with WireGuard.

7. **Use Cloudflare Quick Tunnels for temporary access only.** The `*.trycloudflare.com` URL changes on every restart and is not meant for permanent setups.

8. **Keep cloudflared and Tailscale updated.** Both tools receive regular security patches.

9. **Monitor the endpoint allowlist.** The middleware restricts which API paths are accessible remotely (defined in `_remote_allowed_paths()` in `main.py`). Not all endpoints are exposed.

10. **Purge old audit logs.** Call `tunnel_audit.purge_old(days=90)` periodically to keep the SQLite database from growing indefinitely.

---

## 10. Troubleshooting

### "cloudflared not found"

The binary is not on PATH. Either:
- Install cloudflared and ensure it is in your system PATH.
- Set `cloudflared_path` in `runtime_config.json` to the full path (e.g. `"C:\\Tools\\cloudflared.exe"`).

### Tunnel starts but no URL appears

The `*.trycloudflare.com` URL is parsed from cloudflared's stderr output. It may take 5-10 seconds to appear. Keep polling `/remote/tunnel/status`. If the URL never appears:
- Check that port 8000 (or your configured port) is not blocked by a firewall.
- Check cloudflared's output for errors (visible in the Layla log at DEBUG level).

### 401 Unauthorized / 403 Forbidden

| Status | Meaning | Fix |
|--------|---------|-----|
| 401 | Token was provided but is invalid | Check that you are sending the correct token. Rotate if unsure. |
| 403 (no auth configured) | No `tunnel_token_hash` or `remote_api_key` exists | Run `POST /remote/token/rotate` from localhost to generate one. |
| 403 (endpoint not allowed) | The requested path is not in the remote allowlist | Only certain paths are accessible remotely. Check `_remote_allowed_paths()` in `main.py`. |

### "ip_denied"

Your IP is not in `tunnel_ip_allowlist`. Either add your IP/CIDR to the list in `runtime_config.json`, or clear the list to allow all IPs.

### "token_expired"

The token has exceeded `tunnel_token_ttl_hours`. Rotate:
```bash
curl -X POST http://127.0.0.1:8000/remote/token/rotate
```

### Tunnel keeps dying

Cloudflare Quick Tunnels are ephemeral and may be reclaimed. If the tunnel drops frequently:
- Use the auto-restart mechanism (the system restarts after 3 consecutive health-check failures).
- Consider switching to Tailscale for a more stable connection.

### Tailscale status shows "NeedsLogin"

Run `tailscale login` interactively on the machine, or provide a `tailscale_auth_key` in the config for headless authentication.

### Tailscale Funnel not working

Tailscale Funnel requires:
- Funnel to be enabled in your Tailscale admin console (ACL policy).
- HTTPS certificates to be provisioned (automatic, but may take a moment).
- The machine to be running Tailscale 1.40+ with funnel support.

### Audit database locked

The SQLite audit database (`~/.layla/tunnel_audit.db`) uses a write lock. If you see "database is locked" errors, ensure no other process has an exclusive lock on the file. The connection timeout is 10 seconds.

---

## API Reference (Quick Summary)

| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/remote/tunnel/start` | Start cloudflared quick tunnel |
| `GET` | `/remote/tunnel/status` | Get tunnel running state and URL |
| `POST` | `/remote/tunnel/stop` | Stop the tunnel |
| `GET` | `/remote/tunnel/health` | Health check the active tunnel |
| `POST` | `/remote/token/rotate` | Generate new auth token (shown once) |
| `GET` | `/remote/audit` | Query audit log entries |
| `GET` | `/remote/audit/summary` | Aggregate audit statistics |
| `GET` | `/remote/tailscale/status` | Tailscale VPN status |
| `POST` | `/remote/tailscale/start` | Bring Tailscale up |
| `POST` | `/remote/tailscale/stop` | Bring Tailscale down |
| `POST` | `/remote/tailscale/funnel/start` | Start Tailscale Funnel (public HTTPS) |
| `POST` | `/remote/tailscale/funnel/stop` | Stop Tailscale Funnel |

All management endpoints are accessible from localhost without authentication. Remote access requires a valid Bearer token.
