# Integrations (transports + Discord) — Second sweep

**Area:** `transports/`, `discord_bot/`  
**Status:** Done (phased)  
**Template:** [MODULE_SWEEP_TEMPLATE.md](MODULE_SWEEP_TEMPLATE.md)  
**Alignment:** [OPENCLAW_ALIGNMENT.md](OPENCLAW_ALIGNMENT.md), [OPENCLAW_BRIDGE.md](OPENCLAW_BRIDGE.md)

---

## 1. Scope and entry points

| Surface | Role |
|---------|------|
| **transports/** | Shared `call_layla()` and inbound policy — Slack (Socket Mode), Telegram polling; thin adapters |
| **discord_bot/** | Full Discord bot: voice, TTS, music; calls `/agent` on localhost:8000 |

**Out of scope:** OpenClaw Node gateway; Layla’s bridge is HTTP `POST /agent` (see OPENCLAW_BRIDGE).

---

## 2. Data flow

1. **Outbound:** Transports and Discord bot resolve `LAYLA_API_URL` / `layla_api_url` / default `http://127.0.0.1:8000` via `transports/base.py` (`get_agent_url()`).
2. **Inbound:** Optional allowlist + pairing — `LAYLA_TRANSPORT_ALLOWLIST`, `LAYLA_TRANSPORT_PAIRING_SECRET`, `/pair <secret>`, config `transport_allowlist`, `transport_require_allowlist`; paired IDs in repo-root `.layla_transport_paired.json` (gitignored). See `transports/base.py` docstring and `transports/README.md`.

---

## 3. Safety and invariants

| Invariant | Mechanism |
|-----------|-----------|
| No extra autonomy | Same approval rules as web UI; integrations only forward messages |
| Inbound abuse | Allowlist + optional pairing secret; loggers under `layla.transport` |
| Discord token | Env / config; never commit |

---

## 4. Failure modes and logging

| Failure | Behavior |
|---------|----------|
| Agent down | `LaylaTransportError` / bot connection errors; operator must start FastAPI |
| Allowlist reject | Message dropped or rejected per adapter; see `check_transport_inbound` |

---

## 5. Tests and verification

- Policy helpers: grep / unit tests where present under `agent/tests/` or transport-specific tests.
- **Manual:** Discord `discord_bot/README.md`; transports `transports/README.md`.

---

## 6. Open risks / follow-ups

- **Parity:** Keep transport allowlist behavior documented beside §16 remote auth in IMPLEMENTATION_STATUS when transport policy changes.
- **Discord scope:** Voice/music stack is large; failure analysis for media pipelines lives in bot README + ops runbooks, not duplicated here.
