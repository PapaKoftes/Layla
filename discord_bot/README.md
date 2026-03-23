# Layla Discord Bot — Summon, Chat->Speak, Multi-Source Music

Summon Layla into a Discord voice channel. Chat with her — she replies and speaks back when TTS is on. Play music from YouTube, Spotify, SoundCloud, Bandcamp, or search. Per-channel config.

---

## Quick Start

```bash
# 1. Install dependencies
pip install -r discord_bot/requirements.txt

# 2. Set your Discord token
export DISCORD_TOKEN="your-bot-token"   # or DISCORD_BOT_TOKEN

# 3. Start Layla server (optional but recommended)
cd agent && uvicorn main:app --host 127.0.0.1 --port 8000

# 4. Start the bot
python -m discord_bot.run
```

---

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `DISCORD_TOKEN` | *(required)* | Discord bot token |
| `DISCORD_BOT_TOKEN` | *(required fallback)* | Alias for DISCORD_TOKEN |
| `LAYLA_BASE_URL` | `http://localhost:8000` | Layla API base URL |
| `DISCORD_COMMAND_PREFIX` | `!` | Legacy prefix for text commands |
| `DISCORD_MAX_RESPONSE_CHARS` | `1900` | Max chars per message before splitting |
| `DISCORD_TTS_DEFAULT` | `false` | TTS on by default when summoned |
| `DISCORD_MUSIC_DEFAULT` | `true` | Music enabled by default |

You can also set `discord_bot_token` and `layla_api_url` in `agent/runtime_config.json`.

---

## Flow

1. **/summon** — Layla joins your voice channel and binds to the current text channel.
2. **Chat** — In the bound channel, send any message. She replies in text and (if TTS on) speaks in voice.
3. **@mention** — Works from any channel, even if not summoned.
4. **Music** — `/play` queues tracks; auto-plays when current track ends.
5. **/dismiss** — Layla leaves voice and unbinds.

---

## All Slash Commands

| Command | Description |
|---------|-------------|
| `/summon` | Join your voice channel and bind to this text channel |
| `/dismiss` | Leave voice and unbind text channel |
| `/join` | Join voice only (music, no chat binding) |
| `/leave` | Leave voice channel |
| `/ping` | Check bot latency |
| `/status` | Show Layla server status |
| `/config tts on\|off` | Enable/disable TTS replies in this channel |
| `/config music on\|off` | Enable/disable music in this channel |
| `/ask <question>` | Ask Layla a question (text reply, no TTS) |
| `/note <text>` | Save a note to Layla learnings (operator-initiated only) |
| `/chat_speak <message>` | Ask Layla; she speaks the reply in voice |
| `/tts <message>` | Speak text in voice (TTS) |
| `/say <message>` | Alias for /tts |
| `/play <url\|query>` | Play from YouTube, Spotify, SoundCloud, Bandcamp, or search |
| `/skip` | Skip current track |
| `/queue` | Show current music queue (up to 10 tracks) |
| `/stop` | Stop music and clear queue |
| `/pause` | Pause playback |
| `/resume` | Resume playback |
| `/listen` | Start listening to voice (transcribe + reply + speak) |
| `/stop_listen` | Stop listening and process your voice input |

---

## Setup

### 1. Create a Discord Application

1. Go to [Discord Developer Portal](https://discord.com/developers/applications) → New Application
2. **Bot** → Add Bot
3. Under **Privileged Gateway Intents**, enable:
   - **Message Content Intent**
   - **Server Members Intent**
4. **Reset Token** → copy the token
5. **OAuth2** → URL Generator → Scopes: `bot`, `applications.commands`
6. Bot Permissions: `Send Messages`, `Connect`, `Speak`, `Use Voice Activity`, `Read Message History`
7. Open the generated URL to invite the bot to your server

### 2. Install Dependencies

```bash
# Required
pip install "py-cord[voice]" aiohttp yt-dlp

# Optional: Spotify support
pip install spotdl

# Optional: high-quality TTS
pip install kokoro-onnx soundfile
```

Or use the requirements file:

```bash
pip install -r discord_bot/requirements.txt
```

**FFmpeg** must be installed and in your PATH:
- macOS: `brew install ffmpeg`
- Ubuntu/Debian: `apt install ffmpeg`
- Windows: Download from [ffmpeg.org](https://ffmpeg.org/download.html) and add to PATH

### 3. Spotify Support (optional)

1. Go to [Spotify Developer Dashboard](https://developer.spotify.com/dashboard)
2. Create an application, copy client ID and secret
3. Set environment variables:
   ```bash
   export SPOTIFY_CLIENT_ID="your-client-id"
   export SPOTIFY_CLIENT_SECRET="your-client-secret"
   ```
   Or add to `agent/runtime_config.json`:
   ```json
   "spotify_client_id": "your-client-id",
   "spotify_client_secret": "your-client-secret"
   ```

### 4. Inbound Security (optional)

Same policy as `transports/README.md`:
- `LAYLA_TRANSPORT_ALLOWLIST` — comma-separated Discord user IDs
- `LAYLA_TRANSPORT_PAIRING_SECRET` — users must `/pair <secret>` once
- `transport_require_allowlist` in `runtime_config.json` — deny all if not configured

---

## Troubleshooting

### "FFmpeg not found" or "ffmpeg was not found"
- Install FFmpeg and add it to PATH
- Verify: `ffmpeg -version` in terminal
- On Windows, restart terminal/IDE after adding to PATH

### "DISCORD_TOKEN not set" on startup
- Set `DISCORD_TOKEN` env var or `discord_bot_token` in `agent/runtime_config.json`
- The bot will exit with a clear error message

### Voice not working (can't join/speak)
- Install PyNaCl: `pip install pynacl`
- Or reinstall py-cord with voice: `pip install "py-cord[voice]"`
- Verify FFmpeg is in PATH: `ffmpeg -version`

### TTS not working
- Install kokoro-onnx: `pip install kokoro-onnx soundfile`
- Or pyttsx3 (system voice): `pip install pyttsx3`
- Run diagnostics: `cd agent && python diagnose_startup.py`

### Music not playing / yt-dlp errors
- Update yt-dlp: `pip install --upgrade yt-dlp`
- Geo-blocked videos are skipped automatically
- Spotify: make sure spotdl is installed and credentials are set

### Layla server offline
- Start it: `cd agent && uvicorn main:app --host 127.0.0.1 --port 8000`
- The bot will still start but replies "server offline" until Layla is running
- Check with `/status` command

### Slash commands not appearing
- Wait up to 1 hour for Discord to propagate guild commands
- Or set `DISCORD_GUILD_ID` for instant updates during development
- Commands sync automatically on bot startup

---

## Privacy

The bot runs locally. Chat goes to your Layla instance. TTS uses kokoro-onnx on your machine. Music streams via yt-dlp. No cloud AI, no telemetry.

---

## Roadmap

- **D1** Token + invite; connect to server
- **D2** Channel-bound agent; `/ask` and @mention
- **D3** TTS; voice listen pipeline
- **D4** Music; queue management
- **D5** `/note` for explicit learnings; ethics pillar
