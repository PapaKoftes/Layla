"""
Rich embed builders for Layla Discord Bot.

Aspect-colored, Warframe-themed embeds for all bot responses.
Each aspect gets its own color palette and personality quote.
"""
from __future__ import annotations

import time
from typing import Any

try:
    import discord
    _DISCORD_OK = True
except ImportError:
    discord = None  # type: ignore
    _DISCORD_OK = False


# ── Aspect theme data ────────────────────────────────────────────────────────

ASPECT_THEMES: dict[str, dict[str, Any]] = {
    "morrigan": {
        "color": 0x8B0000,  # Dark red
        "icon": "⚔️",  # Crossed swords
        "title_prefix": "Morrigan",
        "quote": "Direct answers. No hand-holding.",
        "footer_icon": None,
    },
    "nyx": {
        "color": 0x4B0082,  # Indigo
        "icon": "\U0001f52e",  # Crystal ball
        "title_prefix": "Nyx",
        "quote": "Let me think deeply about this...",
        "footer_icon": None,
    },
    "echo": {
        "color": 0x20B2AA,  # Light sea green
        "icon": "\U0001f49a",  # Green heart
        "title_prefix": "Echo",
        "quote": "I hear you. Let's work through this together.",
        "footer_icon": None,
    },
    "eris": {
        "color": 0xFF6347,  # Tomato
        "icon": "\U0001f3b2",  # Game die
        "title_prefix": "Eris",
        "quote": "Oh, this is going to be fun.",
        "footer_icon": None,
    },
    "cassandra": {
        "color": 0x00CED1,  # Dark turquoise
        "icon": "⚡",  # Lightning
        "title_prefix": "Cassandra",
        "quote": "Data doesn't lie. Let me show you.",
        "footer_icon": None,
    },
    "lilith": {
        "color": 0x800080,  # Purple
        "icon": "\U0001f319",  # Crescent moon
        "title_prefix": "Lilith",
        "quote": "Consider the weight of what you're asking.",
        "footer_icon": None,
    },
}

DEFAULT_THEME = {
    "color": 0x5865F2,  # Discord blurple
    "icon": "\U0001f916",
    "title_prefix": "Layla",
    "quote": "How can I help?",
    "footer_icon": None,
}


def _get_theme(aspect: str | None) -> dict:
    """Get theme dict for an aspect name (case-insensitive)."""
    if not aspect:
        return DEFAULT_THEME
    return ASPECT_THEMES.get(aspect.lower().strip(), DEFAULT_THEME)


# ── Embed builders ───────────────────────────────────────────────────────────


def response_embed(
    content: str,
    aspect: str | None = None,
    model: str | None = None,
    latency_ms: float | None = None,
    memory_count: int | None = None,
    confidence: float | None = None,
) -> "discord.Embed":
    """Build a themed embed for a Layla response."""
    if not _DISCORD_OK:
        raise RuntimeError("discord.py not installed")

    theme = _get_theme(aspect)
    # Truncate content to Discord embed limit (4096 chars)
    if len(content) > 4000:
        content = content[:3997] + "..."

    embed = discord.Embed(
        description=content,
        color=theme["color"],
        timestamp=None,
    )

    # Footer with metadata
    footer_parts = []
    if aspect:
        footer_parts.append(f"{theme['icon']} {theme['title_prefix']}")
    if model:
        footer_parts.append(f"Model: {model}")
    if latency_ms is not None:
        footer_parts.append(f"{latency_ms:.0f}ms")
    if memory_count is not None:
        footer_parts.append(f"{memory_count} memories")
    if confidence is not None:
        footer_parts.append(f"Confidence: {confidence:.0%}")

    if footer_parts:
        embed.set_footer(text=" • ".join(footer_parts))

    return embed


def error_embed(
    title: str = "Something went wrong",
    description: str = "",
    aspect: str | None = None,
) -> "discord.Embed":
    """Build an error embed."""
    if not _DISCORD_OK:
        raise RuntimeError("discord.py not installed")

    embed = discord.Embed(
        title=f"❌ {title}",
        description=description[:4000] if description else "An unexpected error occurred.",
        color=0xFF0000,
    )
    theme = _get_theme(aspect)
    embed.set_footer(text=f"{theme['icon']} {theme['title_prefix']} • Error")
    return embed


def status_embed(
    title: str,
    description: str = "",
    fields: dict[str, str] | None = None,
    aspect: str | None = None,
) -> "discord.Embed":
    """Build a status/info embed."""
    if not _DISCORD_OK:
        raise RuntimeError("discord.py not installed")

    theme = _get_theme(aspect)
    embed = discord.Embed(
        title=f"{theme['icon']} {title}",
        description=description[:4000] if description else None,
        color=theme["color"],
    )
    if fields:
        for name, value in fields.items():
            embed.add_field(name=name, value=str(value)[:1024], inline=True)
    embed.set_footer(text=f"{theme['title_prefix']} • {theme['quote']}")
    return embed


def music_embed(
    title: str,
    url: str = "",
    duration: str = "",
    requester: str = "",
    queue_position: int | None = None,
    aspect: str | None = None,
) -> "discord.Embed":
    """Build a music/now-playing embed."""
    if not _DISCORD_OK:
        raise RuntimeError("discord.py not installed")

    theme = _get_theme(aspect)
    embed = discord.Embed(
        title=f"\U0001f3b5 {title}",
        url=url if url else None,
        color=theme["color"],
    )
    if duration:
        embed.add_field(name="Duration", value=duration, inline=True)
    if requester:
        embed.add_field(name="Requested by", value=requester, inline=True)
    if queue_position is not None:
        embed.add_field(name="Position", value=f"#{queue_position}", inline=True)
    embed.set_footer(text=f"{theme['icon']} {theme['title_prefix']}")
    return embed


def help_embed(aspect: str | None = None) -> "discord.Embed":
    """Build a help/commands embed."""
    if not _DISCORD_OK:
        raise RuntimeError("discord.py not installed")

    theme = _get_theme(aspect)
    embed = discord.Embed(
        title=f"{theme['icon']} Layla — Commands",
        description="Your local AI companion, now in Discord.",
        color=theme["color"],
    )
    commands = {
        "\U0001f4ac Chat": (
            "`/ask <question>` — Ask Layla anything\n"
            "`/note <text>` — Save a memory\n"
            "`/chat_speak <msg>` — Ask + speak reply"
        ),
        "\U0001f3a4 Voice": (
            "`/summon` — Join voice channel\n"
            "`/dismiss` — Leave voice channel\n"
            "`/tts <text>` — Speak text in voice\n"
            "`/listen` / `/stop_listen` — Voice-to-text"
        ),
        "\U0001f3b5 Music": (
            "`/play <url|query>` — Play music\n"
            "`/skip` — Skip current track\n"
            "`/queue` — Show queue\n"
            "`/stop` / `/pause` / `/resume`"
        ),
        "⚙️ Config": (
            "`/config tts on|off` — Toggle TTS\n"
            "`/config music on|off` — Toggle music\n"
            "`/status` — Bot status\n"
            "`/ping` — Latency check"
        ),
    }
    for name, value in commands.items():
        embed.add_field(name=name, value=value, inline=False)
    embed.set_footer(text=f"{theme['title_prefix']} • {theme['quote']}")
    return embed
