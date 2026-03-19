"""
Layla Telegram Bot — transport layer. Forwards messages to Layla API, replies in chat.

Setup:
  1. Create bot via @BotFather on Telegram
  2. Set TELEGRAM_BOT_TOKEN env or telegram_bot_token in runtime_config.json
  3. pip install python-telegram-bot
  4. python -m transports.telegram_bot

Requires Layla server at localhost:8000.
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


async def _call_layla(message: str, aspect_id: str = "morrigan") -> str:
    from transports.base import call_layla_async
    return await call_layla_async(message, aspect_id=aspect_id, max_response_chars=4000)


def run_bot():
    try:
        from telegram import Update
        from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
    except ImportError:
        logger.error("python-telegram-bot not installed. pip install python-telegram-bot")
        return None
    token = _get_token()
    if not token:
        logger.error("No TELEGRAM_BOT_TOKEN. Set env or telegram_bot_token in runtime_config.json")
        return None

    async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not update.message or not update.message.text:
            return
        text = update.message.text
        uid = str(update.effective_user.id) if update.effective_user else ""
        from transports.base import check_transport_inbound

        allowed, deny = check_transport_inbound("telegram", uid, text)
        if not allowed:
            if deny:
                await update.message.reply_text(deny[:4000])
            return
        if text.startswith("/"):
            return
        await update.message.chat.send_action("typing")
        reply = await _call_layla(text)
        await update.message.reply_text(reply[:4000])

    async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
        from transports.base import get_inbound_transport_security

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


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
    app = run_bot()
    if app:
        app.run_polling()
