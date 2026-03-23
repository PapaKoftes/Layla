#!/usr/bin/env python3
"""
Run Layla Discord bot.

  python -m discord_bot.run

Requires:
  - DISCORD_TOKEN (or DISCORD_BOT_TOKEN) env var — or discord_bot_token in runtime_config.json
  - pip install "py-cord[voice]" aiohttp
  - FFmpeg in PATH
  - Layla server running (localhost:8000) for /ask, /status, etc.

Optional:
  - pip install yt-dlp          (music)
  - pip install spotdl          (Spotify URLs)
  - pip install kokoro-onnx soundfile  (TTS)
"""
from __future__ import annotations

import asyncio
import logging
import signal
import sys

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("layla.discord")


def _check_layla_server(base_url: str) -> bool:
    """Synchronously ping /health. Returns True if reachable."""
    try:
        import urllib.request
        with urllib.request.urlopen(f"{base_url}/health", timeout=5) as r:
            logger.info("Layla server reachable at %s (HTTP %d)", base_url, r.getcode())
            return True
    except Exception as e:
        logger.warning(
            "Layla server at %s is unreachable: %s\n"
            "  Bot will still start; it will reply 'server offline' to chat until Layla is running.\n"
            "  Start Layla: python -m uvicorn agent.main:app --host 127.0.0.1 --port 8000",
            base_url,
            e,
        )
        return False


def _check_optional_deps() -> None:
    """Log status of optional dependencies."""
    deps = {
        "yt-dlp (music)": "yt_dlp",
        "aiohttp (async HTTP)": "aiohttp",
        "nacl/pynacl (voice)": "nacl",
        "kokoro-onnx (TTS)": "kokoro_onnx",
    }
    for label, mod in deps.items():
        try:
            __import__(mod)
            logger.info("  [OK]    %s", label)
        except ImportError:
            logger.warning("  [MISS]  %s — install for this feature", label)


def main() -> None:
    from discord_bot.config import get_agent_url, get_token
    from discord_bot.bot import _create_bot, _DISCORD_OK

    if not _DISCORD_OK:
        logger.error(
            "py-cord is not installed.\n"
            "  Run: pip install 'py-cord[voice]'\n"
            "  Or:  pip install -r discord_bot/requirements.txt"
        )
        sys.exit(1)

    token = get_token()
    if not token:
        logger.error(
            "No Discord token found.\n"
            "  Set env var DISCORD_TOKEN (or DISCORD_BOT_TOKEN).\n"
            "  Or add 'discord_bot_token' to agent/runtime_config.json.\n"
            "  Get a token at: https://discord.com/developers/applications"
        )
        sys.exit(1)

    base_url = get_agent_url()
    logger.info("Starting Layla Discord bot...")
    logger.info("Optional dependencies:")
    _check_optional_deps()
    _check_layla_server(base_url)

    bot = _create_bot()
    if not bot:
        logger.error("Failed to create bot. Check py-cord installation.")
        sys.exit(1)

    # Graceful shutdown on SIGINT/SIGTERM
    loop = asyncio.get_event_loop()

    def _shutdown(sig_name: str) -> None:
        logger.info("Received %s — shutting down gracefully...", sig_name)
        # Disconnect from all voice channels
        import discord
        for vc in bot.voice_clients:
            try:
                loop.create_task(vc.disconnect(force=True))
            except Exception:
                pass
        loop.create_task(bot.close())

    try:
        for sig in (signal.SIGINT, signal.SIGTERM):
            loop.add_signal_handler(sig, lambda s=sig: _shutdown(s.name))
    except (AttributeError, NotImplementedError):
        # Windows: loop.add_signal_handler not supported on Windows event loops
        # Fall back to KeyboardInterrupt handling only
        pass

    try:
        bot.run(token, reconnect=True)
    except KeyboardInterrupt:
        logger.info("Interrupted — shutting down.")
    except Exception as e:
        logger.exception("Bot crashed: %s", e)
        sys.exit(1)


if __name__ == "__main__":
    main()
