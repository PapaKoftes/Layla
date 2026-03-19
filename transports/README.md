# Layla Chat Transports — Slack, Telegram

Forward messages from Slack and Telegram to Layla. Each transport runs as a separate process and calls the Layla API at localhost:8000.

---

## Slack

**Requires:** `pip install slack-sdk`  
**Tokens:** `SLACK_BOT_TOKEN` (OAuth Bot), `SLACK_APP_TOKEN` (Socket Mode)

1. Create app at [api.slack.com/apps](https://api.slack.com/apps)
2. Enable **Socket Mode** (required for events without public URL)
3. Subscribe to **message.channels** and **message.groups** in Event Subscriptions
4. Add bot to channels
5. Set env: `SLACK_BOT_TOKEN`, `SLACK_APP_TOKEN`
6. Run: `python -m transports.slack_bot`

---

## Telegram

**Requires:** `pip install python-telegram-bot`  
**Token:** `TELEGRAM_BOT_TOKEN` (from @BotFather)

1. Message @BotFather on Telegram, create bot, get token
2. Set env: `TELEGRAM_BOT_TOKEN`
3. Run: `python -m transports.telegram_bot`

---

## Inbound security (OpenClaw-style)

By default, anyone who can message the bot can reach your local Layla. For DM-style bots, **set an allowlist and/or pairing**:

| Mechanism | Env / config | Behavior |
|-----------|----------------|----------|
| Allowlist | `LAYLA_TRANSPORT_ALLOWLIST` (comma-separated user ids) or `transport_allowlist` in `runtime_config.json` | Only listed ids (or `platform:id`, e.g. `discord:123`) can chat. |
| Pairing | `LAYLA_TRANSPORT_PAIRING_SECRET` (env only — do not commit) | User sends once: `/pair <secret>`. Id is stored in repo-root `.layla_transport_paired.json` (gitignored). |
| Strict mode | `transport_require_allowlist`: `true` | If neither allowlist nor pairing secret is set, **all inbound is denied** (catches misconfiguration). |

Platforms: `telegram`, `slack`, `discord` (Discord uses your numeric user id for allowlist).

See [docs/OPENCLAW_ALIGNMENT.md](../docs/OPENCLAW_ALIGNMENT.md).

## Config (optional)

Add to `agent/runtime_config.json`:
```json
"slack_bot_token": "...",
"slack_app_token": "...",
"telegram_bot_token": "...",
"transport_allowlist": "12345,67890",
"transport_require_allowlist": false
```

---

## Layla server

Start Layla first: `cd agent && uvicorn main:app --host 127.0.0.1 --port 8000`
