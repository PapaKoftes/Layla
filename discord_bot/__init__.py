"""
Layla Discord Bot — full capability: chat, voice, TTS, music.

Runs alongside the main Layla server. Connects to localhost:8000 for chat.
Uses kokoro-onnx for TTS, yt-dlp + FFmpeg for music.

Start: python -m discord_bot.run
Config: DISCORD_BOT_TOKEN env, or discord_bot_token in runtime_config.json
"""
