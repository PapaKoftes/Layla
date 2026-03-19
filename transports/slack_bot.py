"""
Layla Slack Bot — transport layer. Forwards messages to Layla API, replies in channel.

Setup:
  1. Create Slack app at api.slack.com/apps
  2. Enable Event Subscriptions, add bot to channels
  3. Set SLACK_BOT_TOKEN env or slack_bot_token in runtime_config.json
  4. pip install slack-sdk
  5. python -m transports.slack_bot

Requires Layla server at localhost:8000.
"""
from __future__ import annotations

import asyncio
import logging
import os
import sys
from pathlib import Path

_agent = Path(__file__).resolve().parent.parent / "agent"
if str(_agent) not in sys.path:
    sys.path.insert(0, str(_agent))

logger = logging.getLogger("layla.slack")


def _get_token() -> str:
    token = os.environ.get("SLACK_BOT_TOKEN", "")
    if token:
        return token
    try:
        import runtime_safety
        cfg = runtime_safety.load_config()
        return cfg.get("slack_bot_token", "") or ""
    except Exception:
        return ""


async def _call_layla(message: str, aspect_id: str = "morrigan") -> str:
    from transports.base import call_layla_async
    return await call_layla_async(message, aspect_id=aspect_id, max_response_chars=3000)


def run_bot():
    try:
        from slack_bolt import App
        from slack_bolt.adapter.socket_mode import SocketModeHandler
    except ImportError:
        logger.error("slack-sdk not installed. pip install slack-sdk")
        return
    token = _get_token()
    if not token:
        logger.error("No SLACK_BOT_TOKEN. Set env or slack_bot_token in runtime_config.json")
        return
    app = App(token=token)

    @app.message()
    def handle_message(message, say, client, logger):
        text = message.get("text", "")
        if not text or message.get("bot_id"):
            return
        uid = str(message.get("user") or "")
        from transports.base import check_transport_inbound

        allowed, deny = check_transport_inbound("slack", uid, text)
        if not allowed:
            if deny:
                thread_ts = message.get("thread_ts") or message.get("ts")
                say(text=deny[:3000], thread_ts=thread_ts)
            return
        thread_ts = message.get("thread_ts") or message.get("ts")
        reply = asyncio.run(_call_layla(text))
        say(text=reply[:3000], thread_ts=thread_ts)

    app_token = os.environ.get("SLACK_APP_TOKEN", "")
    if not app_token:
        logger.error("SLACK_APP_TOKEN required for Socket Mode. Add from Slack app settings.")
        return
    handler = SocketModeHandler(app, app_token)
    handler.start()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
    run_bot()
