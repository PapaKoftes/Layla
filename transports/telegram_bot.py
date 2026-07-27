"""
Layla Telegram transport — long-polling (python-telegram-bot).

Long-polling needs NO public HTTPS endpoint, so this runs happily on a local box
behind NAT (sovereignty-friendly). It is OPTIONAL and OFF by default: start it
yourself with ``python -m transports.telegram_bot``; it is never auto-started
from the core (agent/main.py).

Setup:
  1. Create a bot via @BotFather on Telegram, copy the token.
  2. Set TELEGRAM_BOT_TOKEN env or telegram_bot_token in runtime_config.json.
  3. pip install python-telegram-bot   (optional extra: layla[transports])
  4. python -m transports.telegram_bot

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

logger = logging.getLogger("layla.telegram")

PLATFORM = "telegram"
MAX_CHARS = 4000


def _get_token() -> str:
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    if token:
        return token
    try:
        import runtime_safety
        cfg = runtime_safety.load_config()
        return cfg.get("telegram_bot_token", "") or ""
    except Exception:
        return ""


def build_app():
    """Build the polling Application, or return None if it cannot start.

    Returns None (never raises) when python-telegram-bot is not installed
    (graceful degrade) or when no token is configured (clean refusal).
    """
    try:
        from telegram import Update
        from telegram.ext import (
            Application,
            CommandHandler,
            ContextTypes,
            MessageHandler,
            filters,
        )
    except ImportError:
        logger.error(
            "python-telegram-bot not installed; Telegram transport unavailable. "
            "pip install python-telegram-bot  (or: pip install layla[transports])"
        )
        return None

    token = _get_token()
    if not token:
        logger.error(
            "No TELEGRAM_BOT_TOKEN. Set the env var or telegram_bot_token in runtime_config.json; "
            "refusing to start."
        )
        return None

    from transports.base import TransportAdapter, get_inbound_transport_security

    adapter = TransportAdapter(PLATFORM, max_response_chars=MAX_CHARS)

    async def handle_message(update: "Update", context: "ContextTypes.DEFAULT_TYPE"):
        if not update.message or not update.message.text:
            return
        text = update.message.text
        uid = str(update.effective_user.id) if update.effective_user else ""
        chat_id = update.effective_chat.id if update.effective_chat else uid

        # Shared security gate first (handles /pair, allowlist). A refusal never
        # reaches the agent.
        allowed, deny = adapter.gate(uid, text)
        if not allowed:
            if deny:
                await update.message.reply_text(deny[:MAX_CHARS])
            return
        # Allowed but a bare slash-command (e.g. /pair in open mode): don't forward.
        if text.startswith("/"):
            return
        await update.message.chat.send_action("typing")
        reply = await adapter.run_async(chat_id, text)
        if reply:
            await update.message.reply_text(reply[:MAX_CHARS])

    async def cmd_start(update: "Update", context: "ContextTypes.DEFAULT_TYPE"):
        sec = get_inbound_transport_security()
        extra = ""
        if sec.get("pairing_secret"):
            extra = " If the operator enabled pairing, send `/pair <code>` first."
        elif sec.get("allowlist"):
            extra = " Only allowlisted users can chat."
        await update.message.reply_text("Hi. I'm Layla. Say something and I'll reply." + extra)

    app = Application.builder().token(token).build()
    app.add_handler(CommandHandler("start", cmd_start))
    # /pair must reach handle_message (Telegram treats it as a command otherwise)
    app.add_handler(MessageHandler(filters.TEXT & filters.Regex(r"^/pair\s"), handle_message))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    return app


def run_bot():
    """Build and start long-polling. Returns None if the bot could not start."""
    app = build_app()
    if app is None:
        return None
    app.run_polling()
    return app


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
    run_bot()
