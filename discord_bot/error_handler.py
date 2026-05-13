"""
Global error handler for Layla Discord Bot.

Catches all slash command errors and formats user-friendly responses.
Logs errors to Layla's tool_calls table when available.
"""
from __future__ import annotations

import logging
import traceback

logger = logging.getLogger("layla.discord")

try:
    import discord
    from discord import app_commands
    _DISCORD_OK = True
except ImportError:
    discord = None  # type: ignore
    app_commands = None  # type: ignore
    _DISCORD_OK = False


# ── Error classification ─────────────────────────────────────────────────────

_ERROR_MESSAGES = {
    "MissingPermissions": "I don't have the required permissions for that action.",
    "BotMissingPermissions": "I need additional permissions. Check my role settings.",
    "CommandOnCooldown": "Slow down! Try again in a few seconds.",
    "MissingRequiredArgument": "You're missing a required argument. Check `/help` for usage.",
    "BadArgument": "Invalid argument. Please check the command format.",
    "NotFound": "The requested resource wasn't found.",
    "Forbidden": "I'm not allowed to do that in this server.",
    "HTTPException": "Discord API error. Please try again.",
}


def _classify_error(error: Exception) -> tuple[str, str]:
    """Classify an error and return (title, user-friendly message)."""
    error_type = type(error).__name__

    # Unwrap CommandInvokeError
    if hasattr(error, "original"):
        error = error.original
        error_type = type(error).__name__

    # Check known error types
    for key, message in _ERROR_MESSAGES.items():
        if key in error_type:
            return key, message

    # Connection errors
    if "connect" in str(error).lower() or "timeout" in str(error).lower():
        return "ConnectionError", "Couldn't reach the Layla server. Is it running?"

    # API errors
    if "api" in str(error).lower() or "http" in str(error).lower():
        return "APIError", "There was a problem communicating with Layla's backend."

    # Generic
    return "UnexpectedError", "Something unexpected happened. The error has been logged."


def _log_error_to_layla(error: Exception, command_name: str = "", guild_id: int = 0) -> None:
    """Try to log the error to Layla's tool_calls table."""
    try:
        import sys
        from pathlib import Path
        agent_dir = Path(__file__).resolve().parent.parent / "agent"
        if str(agent_dir) not in sys.path:
            sys.path.insert(0, str(agent_dir))
        from layla.memory.db import insert_tool_call  # type: ignore
        insert_tool_call(
            tool_name=f"discord_{command_name}",
            args_hash="",
            result_ok=False,
            error_code=type(error).__name__,
            duration_ms=0,
        )
    except Exception:
        pass  # Non-critical — don't let logging failures cascade


# ── Error embed builder ──────────────────────────────────────────────────────


def build_error_embed(error: Exception, command_name: str = "") -> "discord.Embed | None":
    """Build an error embed for a failed command."""
    if not _DISCORD_OK:
        return None

    title, message = _classify_error(error)

    embed = discord.Embed(
        title=f"❌ {title}",
        description=message,
        color=0xFF4444,
    )
    if command_name:
        embed.set_footer(text=f"Command: /{command_name}")

    return embed


# ── Setup function ───────────────────────────────────────────────────────────


def setup_error_handler(bot: "discord.ext.commands.Bot") -> None:
    """Register the global error handler on a bot instance."""
    if not _DISCORD_OK:
        return

    @bot.tree.error
    async def on_app_command_error(
        interaction: discord.Interaction,
        error: app_commands.AppCommandError,
    ):
        """Global handler for all slash command errors."""
        command_name = ""
        if interaction.command:
            command_name = interaction.command.name

        # Log
        logger.error(
            "Discord command /%s failed in guild %s: %s",
            command_name,
            interaction.guild_id,
            error,
            exc_info=True,
        )

        # Try to log to Layla's DB
        _log_error_to_layla(error, command_name, interaction.guild_id or 0)

        # Build error embed
        embed = build_error_embed(error, command_name)

        # Try to respond
        try:
            if interaction.response.is_done():
                if embed:
                    await interaction.followup.send(embed=embed, ephemeral=True)
                else:
                    _, msg = _classify_error(error)
                    await interaction.followup.send(f"❌ {msg}", ephemeral=True)
            else:
                if embed:
                    await interaction.response.send_message(embed=embed, ephemeral=True)
                else:
                    _, msg = _classify_error(error)
                    await interaction.response.send_message(f"❌ {msg}", ephemeral=True)
        except Exception as send_err:
            logger.error("Failed to send error response: %s", send_err)
