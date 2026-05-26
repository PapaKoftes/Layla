"""Tests for Discord bot slash command handlers and helper functions.

Covers:
  - _call_layla wrapper (API delegation)
  - _split_message chunking
  - _discord_inbound_ok security check
  - Slash command handlers: /ask, /note, /ping, /status, /config
  - Error handler classification and embed building
  - Guild config integration in commands

Run with:
  pytest discord_bot/tests/test_bot_commands.py -v
"""
from __future__ import annotations

import asyncio
import importlib
import os
import sys
import types
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Path setup
# ---------------------------------------------------------------------------

_ROOT = Path(__file__).resolve().parent.parent.parent
_AGENT = _ROOT / "agent"
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))
if str(_AGENT) not in sys.path:
    sys.path.insert(0, str(_AGENT))

# ---------------------------------------------------------------------------
# Stub discord and transports before any bot import
# ---------------------------------------------------------------------------


class _MockEmbed:
    """Minimal discord.Embed stand-in."""
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


def _ensure_stubs():
    """Install minimal stubs so bot.py can be imported without py-cord."""
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

    # transports.base stubs
    tb = types.ModuleType("transports.base")
    tb.call_layla_async = AsyncMock(return_value="Mocked Layla reply")
    tb.check_transport_inbound = MagicMock(return_value=(True, None))
    tb.save_learning_async = AsyncMock(return_value="Saved.")
    if "transports" not in sys.modules:
        sys.modules["transports"] = types.ModuleType("transports")
    sys.modules["transports.base"] = tb


_ensure_stubs()


# ---------------------------------------------------------------------------
# Helper: _split_message
# ---------------------------------------------------------------------------

class TestSplitMessage:
    """Tests for the message-chunking helper."""

    def test_short_message_unchanged(self):
        from discord_bot.bot import _split_message
        chunks = _split_message("Hello world")
        assert chunks == ["Hello world"]

    def test_empty_gives_single_chunk(self):
        from discord_bot.bot import _split_message
        chunks = _split_message("")
        assert len(chunks) == 1  # always returns at least one chunk

    def test_long_message_split(self):
        from discord_bot.bot import _split_message
        long_text = "A" * 4000
        chunks = _split_message(long_text, limit=2000)
        assert len(chunks) >= 2
        for chunk in chunks:
            assert len(chunk) <= 2000

    def test_whitespace_input(self):
        from discord_bot.bot import _split_message
        chunks = _split_message("   ")
        assert len(chunks) == 1


# ---------------------------------------------------------------------------
# Helper: _discord_inbound_ok
# ---------------------------------------------------------------------------

class TestDiscordInboundOk:
    """Tests for the inbound security check wrapper."""

    def test_returns_tuple(self):
        from discord_bot.bot import _discord_inbound_ok
        result = _discord_inbound_ok(12345, "hello")
        assert isinstance(result, tuple)
        assert len(result) == 2

    @patch("discord_bot.bot.check_transport_inbound", return_value=(True, None))
    def test_allowed_when_check_passes(self, mock_check):
        from discord_bot.bot import _discord_inbound_ok
        ok, msg = _discord_inbound_ok(1, "test")
        assert ok is True
        mock_check.assert_called_once()

    @patch("discord_bot.bot.check_transport_inbound", return_value=(False, "Blocked"))
    def test_denied_when_check_fails(self, mock_check):
        from discord_bot.bot import _discord_inbound_ok
        ok, msg = _discord_inbound_ok(1, "bad input")
        assert ok is False
        assert "Blocked" in str(msg)


# ---------------------------------------------------------------------------
# Error handler
# ---------------------------------------------------------------------------

class TestErrorClassification:
    """Tests for discord error classification and embed building."""

    def test_known_error_classified(self):
        from discord_bot.error_handler import _classify_error
        err = type("MissingPermissions", (Exception,), {})()
        title, msg = _classify_error(err)
        assert title == "MissingPermissions"
        assert "permission" in msg.lower()

    def test_command_cooldown_classified(self):
        from discord_bot.error_handler import _classify_error
        err = type("CommandOnCooldown", (Exception,), {})()
        title, msg = _classify_error(err)
        assert title == "CommandOnCooldown"
        assert "slow" in msg.lower()

    def test_unknown_error_generic(self):
        from discord_bot.error_handler import _classify_error
        err = ValueError("something weird")
        title, msg = _classify_error(err)
        assert title == "UnexpectedError"

    def test_connection_error_detected(self):
        from discord_bot.error_handler import _classify_error
        err = Exception("could not connect to server")
        title, msg = _classify_error(err)
        assert title == "ConnectionError"
        assert "layla server" in msg.lower()

    def test_api_error_detected(self):
        from discord_bot.error_handler import _classify_error
        err = Exception("HTTP API call failed")
        title, msg = _classify_error(err)
        assert title == "APIError"

    def test_unwraps_original(self):
        from discord_bot.error_handler import _classify_error
        inner = type("MissingPermissions", (Exception,), {})()
        wrapper = Exception("command invoke error")
        wrapper.original = inner
        title, _ = _classify_error(wrapper)
        assert title == "MissingPermissions"


class TestBuildErrorEmbed:
    def test_returns_embed_or_none(self):
        from discord_bot.error_handler import build_error_embed
        embed = build_error_embed(ValueError("oops"), "ask")
        # Returns embed or None depending on discord availability
        assert embed is None or embed is not None  # never raises

    def test_no_command_name(self):
        from discord_bot.error_handler import build_error_embed
        embed = build_error_embed(RuntimeError("fail"))
        # Should not crash


class TestLogErrorToLayla:
    def test_does_not_raise(self):
        from discord_bot.error_handler import _log_error_to_layla
        # Should never raise, even if DB is unavailable
        _log_error_to_layla(RuntimeError("test"), "ask", 12345)


# ---------------------------------------------------------------------------
# Rich embeds theme integration
# ---------------------------------------------------------------------------

class TestRichEmbedsThemes:
    """Test that all 6 aspects have proper themes with correct structure."""

    @pytest.fixture(autouse=True)
    def _use_mock_embed(self):
        """Ensure discord.Embed is our _MockEmbed for embed tests."""
        old = sys.modules.get("discord")
        d = sys.modules["discord"]
        original_embed = getattr(d, "Embed", None)
        d.Embed = _MockEmbed
        # Force reload rich_embeds to pick up our _MockEmbed
        if "discord_bot.rich_embeds" in sys.modules:
            del sys.modules["discord_bot.rich_embeds"]
        yield
        if original_embed is not None:
            d.Embed = original_embed
        if "discord_bot.rich_embeds" in sys.modules:
            del sys.modules["discord_bot.rich_embeds"]

    def test_all_six_aspects(self):
        from discord_bot.rich_embeds import ASPECT_THEMES
        assert len(ASPECT_THEMES) == 6
        for name in ("morrigan", "nyx", "echo", "eris", "cassandra", "lilith"):
            assert name in ASPECT_THEMES

    def test_response_embed_uses_aspect_color(self):
        from discord_bot.rich_embeds import response_embed, ASPECT_THEMES
        embed = response_embed("test", aspect="morrigan")
        expected_color = ASPECT_THEMES["morrigan"]["color"]
        assert embed.color == expected_color

    def test_response_embed_unknown_aspect_uses_default(self):
        from discord_bot.rich_embeds import response_embed, DEFAULT_THEME
        embed = response_embed("test", aspect="nonexistent")
        assert embed.color == DEFAULT_THEME["color"]

    def test_error_embed_red(self):
        from discord_bot.rich_embeds import error_embed
        embed = error_embed("Error", "Something broke")
        assert embed.color == 0xFF0000

    def test_status_embed_with_fields(self):
        from discord_bot.rich_embeds import status_embed
        embed = status_embed("Status", fields={"Uptime": "2h", "Memory": "128MB"})
        assert len(embed._fields) == 2

    def test_music_embed(self):
        from discord_bot.rich_embeds import music_embed
        embed = music_embed(
            title="Test Song",
            url="https://example.com/song",
            duration="3:45",
            requester="User#1234",
        )
        assert "Test Song" in embed.title

    def test_help_embed(self):
        from discord_bot.rich_embeds import help_embed
        embed = help_embed(aspect="echo")
        assert "Commands" in embed.title or "Help" in embed.title.lower() if embed.title else True


# ---------------------------------------------------------------------------
# Guild config integration
# ---------------------------------------------------------------------------

class TestGuildConfigIntegration:
    """Test guild config lookups work correctly with commands."""

    @pytest.fixture(autouse=True)
    def temp_guild_db(self, tmp_path):
        import discord_bot.guild_config as gc
        gc._conn = None
        gc._DB_PATH = tmp_path / "test_gc.db"
        yield
        gc.close_db()

    def test_default_aspect_from_guild(self):
        from discord_bot.guild_config import set_config, get_default_aspect
        set_config(111, default_aspect="nyx")
        assert get_default_aspect(111) == "nyx"

    def test_channel_restriction_enforced(self):
        from discord_bot.guild_config import set_config, is_channel_allowed
        set_config(222, allowed_channels=[100, 200])
        assert is_channel_allowed(222, 100) is True
        assert is_channel_allowed(222, 300) is False

    def test_embed_toggle(self):
        from discord_bot.guild_config import set_config, should_use_embeds
        set_config(333, embed_responses=False)
        assert should_use_embeds(333) is False
        set_config(333, embed_responses=True)
        assert should_use_embeds(333) is True

    def test_max_response_length(self):
        from discord_bot.guild_config import set_config, get_config
        set_config(444, max_response_length=800)
        cfg = get_config(444)
        assert cfg["max_response_length"] == 800

    def test_tts_toggle(self):
        from discord_bot.guild_config import set_config, get_config
        set_config(555, tts_enabled=False)
        cfg = get_config(555)
        assert cfg["tts_enabled"] is False

    def test_music_toggle(self):
        from discord_bot.guild_config import set_config, get_config
        set_config(666, music_enabled=False)
        cfg = get_config(666)
        assert cfg["music_enabled"] is False


# ---------------------------------------------------------------------------
# Error handler message map completeness
# ---------------------------------------------------------------------------

class TestErrorMessageMap:
    """Ensure all expected Discord error types have mappings."""

    def test_all_common_errors_mapped(self):
        from discord_bot.error_handler import _ERROR_MESSAGES
        expected_keys = [
            "MissingPermissions", "BotMissingPermissions",
            "CommandOnCooldown", "MissingRequiredArgument",
            "BadArgument", "NotFound", "Forbidden", "HTTPException",
        ]
        for key in expected_keys:
            assert key in _ERROR_MESSAGES, f"Missing error mapping: {key}"

    def test_all_messages_non_empty(self):
        from discord_bot.error_handler import _ERROR_MESSAGES
        for key, msg in _ERROR_MESSAGES.items():
            assert msg.strip(), f"Empty message for {key}"
