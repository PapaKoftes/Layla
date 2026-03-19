# Layla Discord Bot — Summon, Chat→Speak, Multi-Source Music

Summon Layla into a channel. Chat with her — she replies and speaks back when TTS is on. Play music from YouTube, Spotify, SoundCloud, Bandcamp, or search. Per-channel config.

---

## Flow

1. **/summon** — Layla joins your voice channel and binds to the current text channel. She stays until you **/dismiss**.
2. **Chat** — In the bound channel, @mention her. She replies in text and, if TTS is enabled, speaks the reply in voice.
3. **Music** — /play works in any channel where she's in voice. YouTube, Spotify, SoundCloud, Bandcamp, or search query.
4. **Config** — /config tts on|off, /config music on|off — per-channel permissions.

---

## Commands

| Command | Description |
|---------|-------------|
| `/summon` | Join your voice channel and bind to this text channel |
| `/dismiss` | Leave voice and unbind |
| `/join` | Join voice only (music, no chat binding) |
| `/leave` | Leave voice |
| `/config tts on\|off` | Enable/disable TTS replies in this channel |
| `/config music on\|off` | Enable/disable music in this channel |
| `/ask <message>` | Chat with Layla (text reply) |
| `/chat_speak <message>` | Ask Layla; she speaks the reply in voice |
| `/tts <message>` | Speak text in voice (TTS) |
| `/say <message>` | Alias for /tts |
| `/play <url\|query>` | Play from YouTube, Spotify, SoundCloud, Bandcamp, or search |
| `/pause` | Pause playback |
| `/resume` | Resume |
| `/stop` | Stop music and disconnect |
| `/skip` | Skip current track |
| `/queue` | Show queue |
| `/listen` | Start listening to voice — transcribe, reply, speak when done |
| `/stop_listen` | Stop listening and process what you said |

---

## Setup

### 1. Create a Discord Application

1. [Discord Developer Portal](https://discord.com/developers/applications) → New Application
2. **Bot** → Add Bot
3. Enable **Message Content Intent** and **Server Members Intent**
4. **Reset Token** → Copy token
5. **OAuth2** → URL Generator → Scopes: `bot` → Bot Permissions: `Send Messages`, `Connect`, `Speak`, `Use Voice Activity`
6. Open the generated URL to invite the bot to your server

### 2. Install Dependencies

```bash
pip install "py-cord[voice]" yt-dlp aiohttp
```

**Optional — Spotify support:**
```bash
pip install spotdl
```

Add to `agent/runtime_config.json`:
```json
"spotify_client_id": "your-spotify-client-id",
"spotify_client_secret": "your-spotify-client-secret"
```

Get credentials from [Spotify Developer Dashboard](https://developer.spotify.com/dashboard).

**FFmpeg** must be in PATH (required for voice).

### Inbound security

Same policy as [transports/README.md](../transports/README.md): `LAYLA_TRANSPORT_ALLOWLIST`, optional `LAYLA_TRANSPORT_PAIRING_SECRET` (`/pair <secret>` in any text path that talks to Layla), and `transport_require_allowlist` in `runtime_config.json`. Applies to `/ask`, `/chat_speak`, @mention → Layla, and voice → transcribe → Layla.

### 3. Configure Token

**Option A — Environment**
```bash
export DISCORD_BOT_TOKEN="your-bot-token"
```

**Option B — Config**
Add to `agent/runtime_config.json`:
```json
"discord_bot_token": "your-bot-token"
```

### 4. Run

```bash
# Start Layla server first (for chat and TTS)
cd agent && uvicorn main:app --host 127.0.0.1 --port 8000

# In another terminal, start the Discord bot
python -m discord_bot.run
```

---

## Requirements

- **Layla server** running (localhost:8000) for chat and TTS
- **kokoro-onnx** for TTS (`pip install kokoro-onnx soundfile`)
- **yt-dlp** for music (YouTube, SoundCloud, Bandcamp, direct URLs, search)
- **spotdl** (optional) for Spotify URLs
- **FFmpeg** in PATH

---

## Privacy

The bot runs locally. Chat goes to your Layla instance. TTS uses kokoro-onnx on your machine. Music is streamed via yt-dlp — no cloud AI, no telemetry.
