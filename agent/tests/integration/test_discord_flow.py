"""Integration test: Discord bot command → Layla API → rich embed response.

Tests the full flow from slash command invocation through API call to
formatted embed response, using mocked Discord and API layers.
"""
from __future__ import annotations

import asyncio
import sys
import types
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Path setup
# ---------------------------------------------------------------------------

_ROOT = Path(__file__).resolve().parent.parent.parent.parent
_AGENT = _ROOT / "agent"
for p in (_ROOT, _AGENT):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))


# ---------------------------------------------------------------------------
# Stub discord before imports
# ---------------------------------------------------------------------------

class _MockEmbed:
    def __init__(self, **kw):
        self.title = kw.get("title")
        self.description = kw.get("description")
        self.color = kw.get("color")
        self._fields = []
        self._footer = {}

    def set_footer(self, **kw):
        self._footer = kw
        return self

    def add_field(self, **kw):
        self._fields.append(kw)
        return self


def _ensure_discord_stubs():
    for mod_name in ("discord", "discord.ext", "discord.ext.commands",
                     "discord.app_commands", "nacl", "aiohttp"):
        if mod_name not in sys.modules:
            sys.modules[mod_name] = types.ModuleType(mod_name)
    d = sys.modules["discord"]
    d.Intents = MagicMock()
    d.Interaction = MagicMock()
    d.Message = MagicMock()
    d.FFmpegPCMAudio = MagicMock()
    d.PCMVolumeTransformer = MagicMock()
    d.Color = MagicMock()
    d.Embed = _MockEmbed
    d.sinks = MagicMock()
    ext = sys.modules["discord.ext"]
    ext.commands = MagicMock()
    cmd = sys.modules["discord.ext.commands"]
    cmd.Bot = MagicMock()
    aa = sys.modules["discord.app_commands"]
    aa.describe = lambda **kw: (lambda fn: fn)

    tb = types.ModuleType("transports.base")
    tb.call_layla_async = AsyncMock(return_value="Test reply from Layla")
    tb.check_transport_inbound = MagicMock(return_value=(True, None))
    tb.save_learning_async = AsyncMock(return_value="Saved.")
    if "transports" not in sys.modules:
        sys.modules["transports"] = types.ModuleType("transports")
    sys.modules["transports.base"] = tb


_ensure_discord_stubs()


# ---------------------------------------------------------------------------
# Integration: command → API → embed
# ---------------------------------------------------------------------------

class TestDiscordApiFlow:
    """Full flow: user slash command → Layla API call → embed response."""

    @patch("discord_bot.bot.call_layla_async", new_callable=AsyncMock, return_value="The answer is 42")
    def test_ask_flow_calls_layla_and_returns_text(self, mock_call):
        """Simulate /ask → _call_layla → split → response."""
        from discord_bot.bot import _call_layla, _split_message

        loop = asyncio.new_event_loop()
        reply = loop.run_until_complete(_call_layla("What is the answer?"))
        loop.close()

        assert "42" in reply
        chunks = _split_message(reply)
        assert len(chunks) == 1
        assert chunks[0] == "The answer is 42"
        mock_call.assert_called_once()

    def test_long_reply_split_correctly(self):
        """Long API reply gets split into Discord-safe chunks."""
        from discord_bot.bot import _split_message

        long_reply = "A" * 3000
        chunks = _split_message(long_reply, limit=2000)
        assert len(chunks) >= 2
        for chunk in chunks:
            assert len(chunk) <= 2000

    def test_embed_with_aspect_metadata(self):
        """Response embed includes aspect-themed color and metadata."""
        sys.modules["discord"].Embed = _MockEmbed
        if "discord_bot.rich_embeds" in sys.modules:
            del sys.modules["discord_bot.rich_embeds"]

        from discord_bot.rich_embeds import ASPECT_THEMES, response_embed

        embed = response_embed(
            "Test response",
            aspect="morrigan",
            model="local-llama",
            latency_ms=150.0,
            memory_count=5,
        )
        assert embed.color == ASPECT_THEMES["morrigan"]["color"]
        assert embed.description == "Test response"

    def test_error_flow_produces_embed(self):
        """Error in command produces user-friendly error embed."""
        sys.modules["discord"].Embed = _MockEmbed
        if "discord_bot.error_handler" in sys.modules:
            del sys.modules["discord_bot.error_handler"]

        from discord_bot.error_handler import _classify_error, build_error_embed

        error = Exception("could not connect to Layla server")
        title, msg = _classify_error(error)
        assert title == "ConnectionError"
        assert "layla" in msg.lower()

        embed = build_error_embed(error, "ask")
        assert embed is not None


class TestGuildConfigInFlow:
    """Guild config affects command behavior."""

    @pytest.fixture(autouse=True)
    def temp_guild_db(self, tmp_path):
        import discord_bot.guild_config as gc
        gc._conn = None
        gc._DB_PATH = tmp_path / "test_gc.db"
        yield
        gc.close_db()

    def test_channel_restriction_blocks_response(self):
        from discord_bot.guild_config import is_channel_allowed, set_config
        set_config(100, allowed_channels=[200, 300])
        # Channel 999 is not allowed
        assert is_channel_allowed(100, 999) is False
        # Channel 200 is allowed
        assert is_channel_allowed(100, 200) is True

    def test_default_aspect_used_for_embeds(self):
        from discord_bot.guild_config import get_default_aspect, set_config

        set_config(100, default_aspect="nyx")
        aspect = get_default_aspect(100)
        assert aspect == "nyx"

        # Verify the aspect produces the right theme
        sys.modules["discord"].Embed = _MockEmbed
        if "discord_bot.rich_embeds" in sys.modules:
            del sys.modules["discord_bot.rich_embeds"]
        from discord_bot.rich_embeds import ASPECT_THEMES, response_embed

        embed = response_embed("Hello", aspect=aspect)
        assert embed.color == ASPECT_THEMES["nyx"]["color"]

    def test_embed_responses_toggle(self):
        from discord_bot.guild_config import set_config, should_use_embeds
        set_config(100, embed_responses=False)
        assert should_use_embeds(100) is False
        set_config(100, embed_responses=True)
        assert should_use_embeds(100) is True

    def test_max_response_length_limits_chunks(self):
        from discord_bot.bot import _split_message
        from discord_bot.guild_config import get_config, set_config

        set_config(100, max_response_length=500)
        cfg = get_config(100)
        limit = cfg["max_response_length"]

        long_text = "B" * 1200
        chunks = _split_message(long_text, limit=limit)
        assert len(chunks) >= 3
        for chunk in chunks:
            assert len(chunk) <= 500
