# Discord Integration

Two options: **webhooks** (simple messaging) or **full bot** (voice, TTS, music).

---

## Option 1: Webhook (Simple Messaging)

Layla can send messages to your Discord server via webhooks. No bot token required. One-time setup.

---

## 1. Create a Webhook

1. Open your Discord server
2. **Server Settings** (click server name) → **Integrations** → **Webhooks**
3. Click **New Webhook**
4. Name it (e.g. "Layla")
5. Choose the channel where messages should appear
6. Click **Copy Webhook URL**

---

## 2. Configure Layla

**Option A — Config file**

Edit `agent/runtime_config.json`:

```json
{
  "discord_webhook_url": "https://discord.com/api/webhooks/..."
}
```

**Option B — Environment variable**

```bash
export DISCORD_WEBHOOK_URL="https://discord.com/api/webhooks/..."
```

**Option C — Per-call**

Pass `webhook_url` when using the `discord_send` tool.

---

## 3. Use It

Ask Layla: *"Send a message to Discord: Build complete"*

Or use the `discord_notify` skill for notifications.

---

## Skills

- **discord_notify** — Send to Discord (uses config)
- **send_notification** — Discord, Slack, or webhook

---

## Option 2: Full Bot (Voice, TTS, Music)

For voice chat, TTS responses, and music playback, use the full Discord bot.

See **[discord_bot/README.md](../discord_bot/README.md)** for setup.

- `/ask` — Chat with Layla
- `/chat_speak` — Ask Layla; she speaks the reply
- `/tts` — Speak in voice
- `/play` — Play music (YouTube, etc.)
- `/join`, `/leave`, `/pause`, `/stop`, `/skip`

Requires: `py-cord[voice]`, yt-dlp, FFmpeg, kokoro-onnx.

---

## Security

- Webhook URLs and bot tokens are secret. Never commit them.
- `runtime_config.json` is gitignored.
- Webhooks can only *send*; they cannot read messages.
