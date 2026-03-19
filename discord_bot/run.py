#!/usr/bin/env python3
"""
Run Layla Discord bot.

  python -m discord_bot.run

Requires:
  - DISCORD_BOT_TOKEN or discord_bot_token in runtime_config.json
  - pip install "py-cord[voice]" yt-dlp
  - FFmpeg in PATH
  - Layla server running (localhost:8000) for /ask
  - kokoro-onnx for /tts
"""
from __future__ import annotations

import asyncio
import logging
import sys

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("layla.discord")

from discord_bot.config import get_token
from discord_bot.bot import _create_bot


def main():
    token = get_token()
    if not token:
        logger.error(
            "No Discord token. Set DISCORD_BOT_TOKEN env or discord_bot_token in runtime_config.json"
        )
        sys.exit(1)
    bot = _create_bot()
    if not bot:
        sys.exit(1)
    bot.run(token)


if __name__ == "__main__":
    main()
