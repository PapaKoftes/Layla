# Security notes (Layla)

Layla is **local-first**. Threat model assumptions:

- **Single operator** on a trusted machine; binds to `127.0.0.1` by default.
- **Remote mode** (`remote_enabled`): use a strong `remote_api_key`, HTTPS (reverse proxy or cloudflared), and minimal `remote_allow_endpoints`.
- **Sandbox**: file and shell tools are constrained to `sandbox_root`; destructive shell patterns are blocklisted.
- **Approvals**: dangerous tools require explicit approval unless `admin_mode` is enabled (still audited).
- **Zip / path safety**: release updater and ingest paths validate traversal; keep Layla updated.
- **Secrets**: never commit `runtime_config.json` or API keys.

**In-process remote rate limit:** when `remote_enabled`, non-localhost clients are capped per IP using `remote_rate_limit_per_minute` (see `services/remote_rate_limit.py`). For production, also add rate limiting at the reverse proxy, IP allowlists if appropriate, and monitor `.governance/audit.log` + SQLite audit.
