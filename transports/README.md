# Layla Chat Transports — Slack, Telegram

First-class, **optional**, off-by-default chat transports. Each runs as its own
process (never auto-started from `agent/main.py`) and forwards messages to the
Layla API at `localhost:8000`. Slack and Telegram share one base adapter, so
security and conversation handling are identical across them. (Discord lives in
the separate `discord_bot/` package and reuses the same `transports.base` run
path + security gate.)

Neither transport needs a public HTTPS endpoint — Telegram uses long-polling and
Slack uses Socket Mode — so both run on a local box behind NAT (sovereignty
-friendly).

---

## Base adapter contract (`transports/base.py`)

Every inbound turn flows through `TransportAdapter`:

```
message-in  ->  inbound security gate  ->  run the agent  ->  reply-out
                (allowlist / pairing)      (allow_write =
                                             allow_run = FORCED False)
```

- `adapter.gate(user_id, text) -> (allowed, deny_msg)` — the shared inbound
  policy. A refused sender never reaches the agent.
- `adapter.run_async(chat_id, text)` / `run_sync(...)` — run the agent for an
  already-gated turn. **`allow_write` and `allow_run` are hard-coded to `False`**;
  there is deliberately no parameter to raise them.
- `adapter.handle_inbound_async(...)` / `handle_inbound_sync(...)` — convenience
  one-shots: gate, then (if allowed) run and record history. Return an
  `InboundResult(allowed, reply, ran_agent)`.
- **Conversation history** is bounded (`history_turns`, default 6) and keyed by
  chat id, so each chat gets its own short rolling context with no cross-chat
  bleed. History is in-memory only; it is passed to the agent as `context`.

### Security posture

Transport turns are **untrusted input**, so the adapter is fail-closed:

- `allow_write` / `allow_run` are **forced `False`** on every agent call — a
  remote chat can never get filesystem-write or code-execution. This mirrors the
  router's own fail-closed stance (`/agent` and `/v1` also drop write/run for
  non-local callers).
- The inbound **allowlist / pairing** gate runs before the agent is ever called.
- Tokens and config are never echoed back into a reply — replies carry only
  agent text.

---

## Slack

**Requires:** `pip install slack-bolt` (or `pip install layla[transports]`)
**Tokens:** `SLACK_BOT_TOKEN` (`xoxb-…`, OAuth Bot) and `SLACK_APP_TOKEN`
(`xapp-…`, Socket Mode). The bot refuses to start without both.

1. Create an app at [api.slack.com/apps](https://api.slack.com/apps)
2. Enable **Socket Mode** (required for events without a public URL)
3. Subscribe to **message.channels** and **message.groups** in Event Subscriptions
4. Add the bot to channels
5. Set env: `SLACK_BOT_TOKEN`, `SLACK_APP_TOKEN`
6. Run: `python -m transports.slack_bot`

---

## Telegram

**Requires:** `pip install python-telegram-bot` (or `pip install layla[transports]`)
**Token:** `TELEGRAM_BOT_TOKEN` (from @BotFather). The bot refuses to start without it.

1. Message @BotFather on Telegram, create a bot, get the token
2. Set env: `TELEGRAM_BOT_TOKEN`
3. Run: `python -m transports.telegram_bot`

---

## Inbound security (optional)

By default, anyone who can message the bot can reach your local Layla. For
DM-style bots, **set an allowlist and/or pairing**:

| Mechanism | Env / config | Behavior |
|-----------|----------------|----------|
| Allowlist | `LAYLA_TRANSPORT_ALLOWLIST` (comma-separated user ids) or `transport_allowlist` in `runtime_config.json` | Only listed ids (or `platform:id`, e.g. `telegram:123`) can chat. |
| Pairing | `LAYLA_TRANSPORT_PAIRING_SECRET` (env only — do not commit) | User sends once: `/pair <secret>`. Id is stored in repo-root `.layla_transport_paired.json` (gitignored). |
| Strict mode | `transport_require_allowlist`: `true` | If neither allowlist nor pairing secret is set, **all inbound is denied** (catches misconfiguration). |

Platforms: `telegram`, `slack`, `discord`.

See docs/ALIGNMENT_NOTE.md.

## Config (optional)

Add to `agent/runtime_config.json`:
```json
"slack_bot_token": "...",
"slack_app_token": "...",
"telegram_bot_token": "...",
"transport_allowlist": "12345,67890",
"transport_require_allowlist": false
```

## Optional dependencies

Suggested `pyproject.toml` extra (see the report — not yet added):
```toml
transports = [
    "python-telegram-bot>=21,<22",   # Telegram long-polling (MIT)
    "slack-bolt>=1.18,<2",           # Slack Socket Mode (MIT; pulls slack-sdk)
]
```
The async run path uses `httpx` (already a Layla `[core]` dependency), so no
extra HTTP client is required.

---

## Layla server

Start Layla first: `cd agent && uvicorn main:app --host 127.0.0.1 --port 8000`
