# Layla Discord Bot -- Setup Guide

This guide walks you through setting up the Layla AI agent's Discord bot integration. The bot provides 20+ slash commands for chat, voice TTS, music playback, and per-guild configuration.

---

## 1. Prerequisites

**Required:**

- Python 3.10+
- [py-cord](https://docs.pycord.dev/) with voice support: `pip install "py-cord[voice]>=2.4.0"`
- aiohttp: `pip install aiohttp>=3.9.0`
- FFmpeg installed and available in your system PATH
- The Layla agent server running at `http://127.0.0.1:8000`

**Optional (feature-specific):**

| Package | Feature | Install |
|---------|---------|---------|
| yt-dlp | YouTube/SoundCloud/Bandcamp music | `pip install yt-dlp` |
| spotdl | Spotify URL support | `pip install spotdl` |
| kokoro-onnx + soundfile | Text-to-speech in voice | `pip install kokoro-onnx soundfile` |
| faster-whisper | Voice transcription (STT) | `pip install faster-whisper` |
| PyNaCl | Voice connectivity (usually bundled with py-cord[voice]) | `pip install pynacl` |

**Install all required dependencies at once:**

```
pip install -r discord_bot/requirements.txt
```

---

## 2. Creating a Discord Application and Bot

1. Go to the [Discord Developer Portal](https://discord.com/developers/applications).
2. Click **New Application**, give it a name (e.g., "Layla"), and create it.
3. Navigate to **Bot** in the left sidebar.
4. Click **Reset Token** (or **Copy** if this is a new bot) and save the token securely. You will need it in the next step.
5. Under **Privileged Gateway Intents**, enable:
   - **Message Content Intent** (required for reading messages in bound channels)
   - **Server Members Intent** is not required but can be enabled if needed later.
6. Navigate to **OAuth2 > URL Generator**:
   - Under **Scopes**, select `bot` and `applications.commands`.
   - Under **Bot Permissions**, select:
     - Send Messages
     - Embed Links
     - Use Slash Commands
     - Read Message History
     - Connect (voice)
     - Speak (voice)
   - The numeric permissions value used by the installer is `3267584`.
7. Copy the generated URL and open it in your browser to invite the bot to your server.

Alternatively, you can generate an invite URL with the built-in installer (see Section 4).

---

## 3. Configuring the Bot Token

The bot reads its token from multiple sources, checked in this order:

1. Environment variable `DISCORD_TOKEN`
2. Environment variable `DISCORD_BOT_TOKEN`
3. The `discord_bot_token` key in `agent/runtime_config.json`

**Option A -- runtime_config.json (recommended):**

Open or create `agent/runtime_config.json` and add:

```json
{
  "discord_bot_token": "YOUR_BOT_TOKEN_HERE"
}
```

**Option B -- Environment variable:**

```
set DISCORD_TOKEN=YOUR_BOT_TOKEN_HERE
```

**Option C -- Run the interactive installer:**

```
python -m discord_bot.installer
```

The installer wizard walks you through token validation, API URL configuration, writing config files, and generating an invite URL.

---

## 4. Starting the Bot

### Standalone mode

Make sure the Layla agent server is running first:

```
python -m uvicorn agent.main:app --host 127.0.0.1 --port 8000
```

Then start the Discord bot:

```
python -m discord_bot.run
```

The bot will log its status, check optional dependencies, ping the Layla server, and connect to Discord. If the Layla server is unreachable at startup, the bot will still start -- it will reply with "server offline" messages until the server comes up.

### Auto-start mode (launched with the Layla server)

Add both keys to `agent/runtime_config.json`:

```json
{
  "discord_bot_token": "YOUR_BOT_TOKEN_HERE",
  "discord_bot_autostart": true
}
```

When the Layla server starts, it will automatically spawn the Discord bot in a background daemon thread. No separate process needed.

---

## 5. Bot Commands Overview

### Voice and Session

| Command | Description |
|---------|-------------|
| `/summon` | Join your voice channel and bind to the current text channel. Layla responds to all messages in the bound channel. |
| `/dismiss` | Leave voice, unbind the text channel, and clear the music queue. |
| `/join` | Join your voice channel for music only (no text channel binding). |
| `/leave` | Leave the voice channel. |

### Chat and AI

| Command | Description |
|---------|-------------|
| `/ask <question>` | Ask Layla a question; she replies with text. |
| `/chat_speak <message>` | Ask Layla and she speaks the reply in voice. |
| `/note <text>` | Save a note to Layla's learnings (operator-initiated). |

### Text-to-Speech

| Command | Description |
|---------|-------------|
| `/tts <message>` | Speak the given text in the voice channel. |
| `/say <message>` | Alias for `/tts`. |

### Voice Transcription

| Command | Description |
|---------|-------------|
| `/listen` | Start recording voice input. Layla transcribes, replies, and optionally speaks. |
| `/stop_listen` | Stop recording and process captured audio. |

### Music

| Command | Description |
|---------|-------------|
| `/play <url or query>` | Play from YouTube, Spotify, SoundCloud, Bandcamp, or search. |
| `/skip` | Skip the current track. |
| `/queue` | Show the current music queue (up to 10 tracks). |
| `/stop` | Stop playback and clear the queue. |
| `/pause` | Pause the current track. |
| `/resume` | Resume paused playback. |

### Utility

| Command | Description |
|---------|-------------|
| `/config <setting> <value>` | Per-channel config: `tts on\|off` or `music on\|off`. |
| `/status` | Show Layla server health and connectivity. |
| `/ping` | Check bot latency to Discord. |

### Passive Responses

When summoned (`/summon`), Layla automatically replies to all messages in the bound text channel. She also responds to @mentions in any channel. If TTS is enabled and she is in voice, she speaks her replies aloud.

---

## 6. Per-Guild Configuration

Each server (guild) gets its own configuration stored in a local SQLite database at `discord_bot/guild_config.db`. This is managed through `discord_bot/guild_config.py`.

### Available settings

| Setting | Type | Default | Description |
|---------|------|---------|-------------|
| `default_aspect` | string | `""` (Layla default) | Default personality aspect for the guild (e.g., `morrigan`, `nyx`, `echo`, `eris`, `cassandra`, `lilith`). |
| `allowed_channels` | list | `[]` (all channels) | Restrict bot responses to specific channel IDs. Empty means no restrictions. |
| `admin_roles` | list | `[]` | Role IDs that can manage bot configuration. |
| `tts_enabled` | bool | `true` | Whether TTS is available in this guild. |
| `music_enabled` | bool | `true` | Whether music playback is available. |
| `max_response_length` | int | `1900` | Maximum characters per message before splitting. |
| `auto_respond` | bool | `false` | Whether to respond to all messages without being summoned. |
| `embed_responses` | bool | `true` | Use rich embeds (aspect-themed colors and formatting) for responses. |

### Aspect themes

Rich embeds are styled per-aspect with unique colors:

- **Morrigan** -- Dark red, direct and blunt
- **Nyx** -- Indigo, deep and thoughtful
- **Echo** -- Sea green, empathetic and collaborative
- **Eris** -- Tomato red, playful and chaotic
- **Cassandra** -- Dark turquoise, data-driven and precise
- **Lilith** -- Purple, contemplative and weighty

### In-chat configuration

Use the `/config` slash command for quick per-channel toggles:

```
/config tts on
/config tts off
/config music on
/config music off
```

---

## 7. Troubleshooting

### "py-cord is not installed"

```
pip install "py-cord[voice]"
```

Make sure you do not have both `discord.py` and `py-cord` installed simultaneously -- they conflict. Uninstall one first:

```
pip uninstall discord.py
pip install "py-cord[voice]"
```

### "No Discord token found"

The bot checks three sources in order: `DISCORD_TOKEN` env var, `DISCORD_BOT_TOKEN` env var, then `discord_bot_token` in `agent/runtime_config.json`. Make sure at least one is set. Run the installer for guided setup:

```
python -m discord_bot.installer
```

### "Layla server is offline"

The bot needs the Layla agent API to answer questions. Start it with:

```
python -m uvicorn agent.main:app --host 127.0.0.1 --port 8000
```

The bot will still run while the server is down -- it just replies with an offline message until the server is reachable.

### Voice connection fails ("Could not join voice channel")

- Confirm FFmpeg is installed and in your system PATH. Test with: `ffmpeg -version`
- Confirm PyNaCl is installed: `pip install pynacl`
- Make sure the bot has **Connect** and **Speak** permissions in the voice channel.

### TTS says "TTS unavailable"

Install the TTS dependencies:

```
pip install kokoro-onnx soundfile
```

### Music says "yt-dlp is not installed"

```
pip install yt-dlp
```

For Spotify URL support, also install spotdl:

```
pip install spotdl
```

### Slash commands not appearing

- Slash commands sync automatically when the bot starts (`on_ready`). This can take up to an hour for global commands to propagate across Discord.
- If commands still do not appear, try kicking and re-inviting the bot with the `applications.commands` scope enabled.
- Check the bot logs for "Command sync failed" errors.

### Bot responds to nothing

- If using `/summon`, the bot only responds in the bound text channel. Try @mentioning the bot in any channel to verify it is online.
- Check that **Message Content Intent** is enabled in the Developer Portal under Bot > Privileged Gateway Intents.
- Verify the bot has **Read Message History** and **Send Messages** permissions in the channel.

### Auto-start not working

Confirm both keys are present in `agent/runtime_config.json`:

```json
{
  "discord_bot_token": "YOUR_TOKEN",
  "discord_bot_autostart": true
}
```

Check the Layla server logs for "Discord bot auto-start thread launched" or related error messages.
