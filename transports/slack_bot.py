"""
Layla Slack transport — Socket Mode (slack-bolt).

Socket Mode needs NO public inbound endpoint (Slack opens the websocket to you),
so this runs on a local box behind NAT. It is OPTIONAL and OFF by default: start
it yourself with ``python -m transports.slack_bot``; it is never auto-started from
the core (agent/main.py).

Setup:
  1. Create a Slack app at api.slack.com/apps.
  2. Enable Socket Mode; subscribe to message.channels / message.groups events.
  3. Add the bot to channels.
  4. Set SLACK_BOT_TOKEN (xoxb-…) and SLACK_APP_TOKEN (xapp-…) env or config.
  5. pip install slack-bolt   (optional extra: layla[transports])
  6. python -m transports.slack_bot

Security: every inbound turn goes through transports.base.TransportAdapter, which
enforces the shared allowlist/pairing gate and FORCES allow_write=allow_run=False.
Requires the Layla server at localhost:8000.
"""
from __future__ import annotations

import logging
import os
import sys
from pathlib import Path

_agent = Path(__file__).resolve().parent.parent / "agent"
if str(_agent) not in sys.path:
    sys.path.insert(0, str(_agent))

logger = logging.getLogger("layla.slack")

PLATFORM = "slack"
MAX_CHARS = 3000


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


def _get_app_token() -> str:
    token = os.environ.get("SLACK_APP_TOKEN", "")
    if token:
        return token
    try:
        import runtime_safety
        cfg = runtime_safety.load_config()
        return cfg.get("slack_app_token", "") or ""
    except Exception:
        return ""


def build_app():
    """Build the Socket Mode handler, or return None if it cannot start.

    Returns (never raises) None when slack-bolt is not installed (graceful
    degrade) or when either required token is missing (clean refusal).
    Returns a started-ready ``SocketModeHandler`` otherwise.
    """
    try:
        from slack_bolt import App
        from slack_bolt.adapter.socket_mode import SocketModeHandler
    except ImportError:
        logger.error(
            "slack-bolt not installed; Slack transport unavailable. "
            "pip install slack-bolt  (or: pip install layla[transports])"
        )
        return None

    token = _get_token()
    if not token:
        logger.error(
            "No SLACK_BOT_TOKEN. Set the env var or slack_bot_token in runtime_config.json; "
            "refusing to start."
        )
        return None
    app_token = _get_app_token()
    if not app_token:
        logger.error(
            "No SLACK_APP_TOKEN (required for Socket Mode). Set the env var or slack_app_token in "
            "runtime_config.json; refusing to start."
        )
        return None

    from transports.base import TransportAdapter

    adapter = TransportAdapter(PLATFORM, max_response_chars=MAX_CHARS)
    app = App(token=token)

    @app.message()
    def handle_message(message, say, client, logger):  # noqa: A002 (bolt injects `logger`)
        text = message.get("text", "")
        if not text or message.get("bot_id"):
            return
        uid = str(message.get("user") or "")
        chat_id = message.get("channel") or uid
        thread_ts = message.get("thread_ts") or message.get("ts")
        result = adapter.handle_inbound_sync(chat_id=chat_id, user_id=uid, text=text)
        if result.reply:
            say(text=result.reply[:MAX_CHARS], thread_ts=thread_ts)

    return SocketModeHandler(app, app_token)


def run_bot():
    """Build and start Socket Mode. Returns None if the bot could not start."""
    handler = build_app()
    if handler is None:
        return None
    handler.start()
    return handler


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
    run_bot()
