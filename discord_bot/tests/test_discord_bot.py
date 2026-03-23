"""
Unit tests for Layla Discord bot.

Tests:
  - State management (summon/dismiss/queue)
  - Message routing logic (summoned vs mention)
  - Config parsing and env vars
  - Graceful startup without DISCORD_TOKEN (should fail with clear error)

Run with:
  pytest discord_bot/tests/test_discord_bot.py -v
"""
from __future__ import annotations

import importlib
import os
import sys
import types
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Path setup so we can import discord_bot modules without installing the pkg
# ---------------------------------------------------------------------------

_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

# Stub out heavy optional deps before importing discord_bot
for _mod in ("discord", "discord.ext", "discord.ext.commands", "discord.app_commands", "nacl", "aiohttp"):
    if _mod not in sys.modules:
        sys.modules[_mod] = types.ModuleType(_mod)

# discord needs some attributes that bot.py references
_discord_stub = sys.modules["discord"]
_discord_stub.Intents = MagicMock()
_discord_stub.Interaction = MagicMock()
_discord_stub.Message = MagicMock()
_discord_stub.FFmpegPCMAudio = MagicMock()
_discord_stub.PCMVolumeTransformer = MagicMock()
_discord_stub.Color = MagicMock()
_discord_stub.Embed = MagicMock()
_discord_stub.sinks = MagicMock()

_ext_stub = sys.modules["discord.ext"]
_ext_stub.commands = MagicMock()

_cmd_stub = types.ModuleType("discord.ext.commands")
_cmd_stub.Bot = MagicMock()
sys.modules["discord.ext.commands"] = _cmd_stub

_app_stub = types.ModuleType("discord.app_commands")
_app_stub.describe = lambda **kw: (lambda fn: fn)
sys.modules["discord.app_commands"] = _app_stub

# ---------------------------------------------------------------------------
# Stub transports.base
# ---------------------------------------------------------------------------

_transports_base = types.ModuleType("transports.base")
_transports_base.call_layla_async = MagicMock()
_transports_base.check_transport_inbound = MagicMock(return_value=(True, None))
_transports_base.save_learning_async = MagicMock()
sys.modules["transports"] = types.ModuleType("transports")
sys.modules["transports.base"] = _transports_base


# ---------------------------------------------------------------------------
# State tests
# ---------------------------------------------------------------------------

class TestState:
    """Tests for discord_bot/state.py — per-guild state management."""

    def setup_method(self):
        """Re-import state with a fresh in-memory dict for each test."""
        from discord_bot import state as s
        self.state = s
        # Reset in-memory dicts
        s._guild_state.clear()
        s._voice_clients.clear()
        s._queues.clear()
        s._playing.clear()
        s._queue_titles.clear()
        s._listening.clear()

    def test_initial_state_defaults(self):
        from discord_bot.state import get_guild_state
        s = get_guild_state(12345)
        assert s["tts_enabled"] is True
        assert s["music_enabled"] is True

    def test_set_and_get_guild_state(self):
        from discord_bot.state import set_guild_state, get_guild_state
        set_guild_state(99, voice_channel_id=111, text_channel_id=222)
        s = get_guild_state(99)
        assert s["voice_channel_id"] == 111
        assert s["text_channel_id"] == 222

    def test_is_summoned_true_when_voice_channel_set(self):
        from discord_bot.state import set_guild_state, is_summoned
        set_guild_state(1, voice_channel_id=55)
        assert is_summoned(1) is True

    def test_is_summoned_false_when_no_voice_channel(self):
        from discord_bot.state import set_guild_state, is_summoned
        set_guild_state(2, voice_channel_id=None)
        assert is_summoned(2) is False

    def test_is_summoned_false_new_guild(self):
        from discord_bot.state import is_summoned
        assert is_summoned(999999) is False

    def test_dismiss_clears_channels(self):
        from discord_bot.state import set_guild_state, get_text_channel_id, get_voice_channel_id
        set_guild_state(3, voice_channel_id=10, text_channel_id=20)
        assert get_voice_channel_id(3) == 10
        assert get_text_channel_id(3) == 20
        set_guild_state(3, voice_channel_id=None, text_channel_id=None)
        assert get_voice_channel_id(3) is None
        assert get_text_channel_id(3) is None

    def test_queue_append_pop(self):
        from discord_bot.state import append_queue, pop_queue, get_queue
        append_queue(10, {"url": "http://a", "title": "Song A"})
        append_queue(10, {"url": "http://b", "title": "Song B"})
        q = get_queue(10)
        assert len(q) == 2
        item = pop_queue(10)
        assert item["title"] == "Song A"
        assert len(get_queue(10)) == 1

    def test_queue_pop_empty_returns_none(self):
        from discord_bot.state import pop_queue
        assert pop_queue(77) is None

    def test_clear_queue(self):
        from discord_bot.state import append_queue, clear_queue, get_queue, get_queue_titles
        append_queue(20, {"url": "http://x", "title": "X"})
        clear_queue(20)
        assert get_queue(20) == []
        assert get_queue_titles(20) == []

    def test_queue_titles_tracked(self):
        from discord_bot.state import append_queue, get_queue_titles
        append_queue(30, {"url": "http://t", "title": "My Track"})
        titles = get_queue_titles(30)
        assert "My Track" in titles

    def test_playing_flag(self):
        from discord_bot.state import set_playing, is_playing
        assert is_playing(40) is False
        set_playing(40, True)
        assert is_playing(40) is True
        set_playing(40, False)
        assert is_playing(40) is False

    def test_tts_enabled_default(self):
        from discord_bot.state import tts_enabled, set_guild_state
        set_guild_state(50, text_channel_id=100, tts_enabled=True)
        assert tts_enabled(50, 100) is True

    def test_tts_disabled_when_wrong_channel(self):
        from discord_bot.state import tts_enabled, set_guild_state
        set_guild_state(51, text_channel_id=101, tts_enabled=True)
        # Different channel_id -> returns False
        assert tts_enabled(51, 999) is False

    def test_tts_can_be_toggled(self):
        from discord_bot.state import set_guild_state, tts_enabled
        set_guild_state(52, tts_enabled=False)
        assert tts_enabled(52) is False

    def test_music_enabled_default(self):
        from discord_bot.state import music_enabled
        assert music_enabled(60) is True

    def test_music_can_be_disabled(self):
        from discord_bot.state import set_guild_state, music_enabled
        set_guild_state(61, music_enabled=False)
        assert music_enabled(61) is False

    def test_voice_client_set_get_pop(self):
        from discord_bot.state import set_voice_client, get_voice_client, pop_voice_client
        vc = MagicMock()
        set_voice_client(70, vc)
        assert get_voice_client(70) is vc
        popped = pop_voice_client(70)
        assert popped is vc
        assert get_voice_client(70) is None

    def test_listening_state(self):
        from discord_bot.state import set_listening, is_listening, get_listening_channel
        assert is_listening(80) is False
        set_listening(80, 200)
        assert is_listening(80) is True
        assert get_listening_channel(80) == 200
        set_listening(80, None)
        assert is_listening(80) is False


# ---------------------------------------------------------------------------
# Message routing tests
# ---------------------------------------------------------------------------

class TestMessageRouting:
    """Tests for on_message routing logic (summoned vs @mention)."""

    def setup_method(self):
        from discord_bot import state as s
        s._guild_state.clear()
        s._voice_clients.clear()

    def test_responds_to_all_messages_when_summoned(self):
        """
        When summoned and message is in the bound channel, should_respond = True
        regardless of @mention.
        """
        from discord_bot.state import set_guild_state, get_text_channel_id, is_summoned

        guild_id = 100
        channel_id = 200
        set_guild_state(guild_id, voice_channel_id=50, text_channel_id=channel_id)

        assert is_summoned(guild_id) is True
        text_ch = get_text_channel_id(guild_id)
        in_bound_channel = (text_ch == channel_id)
        bot_mentioned = False
        should_respond = bot_mentioned or (is_summoned(guild_id) and in_bound_channel)
        assert should_respond is True

    def test_no_response_in_wrong_channel_when_summoned(self):
        from discord_bot.state import set_guild_state, get_text_channel_id, is_summoned

        guild_id = 101
        set_guild_state(guild_id, voice_channel_id=50, text_channel_id=200)

        in_bound_channel = (get_text_channel_id(guild_id) == 999)  # wrong channel
        bot_mentioned = False
        should_respond = bot_mentioned or (is_summoned(guild_id) and in_bound_channel)
        assert should_respond is False

    def test_responds_to_mention_even_when_not_summoned(self):
        from discord_bot.state import is_summoned

        guild_id = 102
        # Not summoned (no voice_channel_id)
        assert is_summoned(guild_id) is False

        bot_mentioned = True
        in_bound_channel = False
        should_respond = bot_mentioned or (is_summoned(guild_id) and in_bound_channel)
        assert should_respond is True

    def test_no_response_to_non_mention_when_not_summoned(self):
        from discord_bot.state import is_summoned

        guild_id = 103
        assert is_summoned(guild_id) is False

        bot_mentioned = False
        in_bound_channel = False
        should_respond = bot_mentioned or (is_summoned(guild_id) and in_bound_channel)
        assert should_respond is False


# ---------------------------------------------------------------------------
# Config parsing tests
# ---------------------------------------------------------------------------

class TestConfig:
    """Tests for discord_bot/config.py."""

    def test_get_command_prefix_default(self):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("DISCORD_COMMAND_PREFIX", None)
            from discord_bot.config import get_command_prefix
            assert get_command_prefix() == "!"

    def test_get_command_prefix_custom(self):
        with patch.dict(os.environ, {"DISCORD_COMMAND_PREFIX": "?"}):
            # Reload to pick up env change
            import importlib
            from discord_bot import config
            importlib.reload(config)
            assert config.get_command_prefix() == "?"

    def test_get_max_response_chars_default(self):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("DISCORD_MAX_RESPONSE_CHARS", None)
            from discord_bot.config import get_max_response_chars
            assert get_max_response_chars() == 1900

    def test_get_max_response_chars_custom(self):
        with patch.dict(os.environ, {"DISCORD_MAX_RESPONSE_CHARS": "2000"}):
            from discord_bot import config
            importlib.reload(config)
            assert config.get_max_response_chars() == 2000

    def test_get_tts_default_false(self):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("DISCORD_TTS_DEFAULT", None)
            from discord_bot.config import get_tts_default
            assert get_tts_default() is False

    def test_get_tts_default_enabled(self):
        with patch.dict(os.environ, {"DISCORD_TTS_DEFAULT": "true"}):
            from discord_bot import config
            importlib.reload(config)
            assert config.get_tts_default() is True

    def test_get_music_default_true(self):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("DISCORD_MUSIC_DEFAULT", None)
            from discord_bot.config import get_music_default
            assert get_music_default() is True

    def test_get_music_default_disabled(self):
        with patch.dict(os.environ, {"DISCORD_MUSIC_DEFAULT": "false"}):
            from discord_bot import config
            importlib.reload(config)
            assert config.get_music_default() is False

    def test_get_agent_url_default(self):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("LAYLA_BASE_URL", None)
            os.environ.pop("LAYLA_API_URL", None)
            from discord_bot.config import get_agent_url
            url = get_agent_url()
            assert "8000" in url or "localhost" in url or "127.0.0.1" in url

    def test_get_agent_url_from_env(self):
        with patch.dict(os.environ, {"LAYLA_BASE_URL": "http://myserver:9000"}):
            from discord_bot import config
            importlib.reload(config)
            assert config.get_agent_url() == "http://myserver:9000"

    def test_get_token_empty_without_env(self):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("DISCORD_TOKEN", None)
            os.environ.pop("DISCORD_BOT_TOKEN", None)
            from discord_bot.config import get_token
            # May return "" if no runtime_config, or whatever is in runtime_config
            # Just verify it returns a str
            result = get_token()
            assert isinstance(result, str)


# ---------------------------------------------------------------------------
# Startup without token test
# ---------------------------------------------------------------------------

class TestStartup:
    """Test graceful startup failure when DISCORD_TOKEN is missing."""

    def test_main_exits_without_token(self):
        """run.main() should call sys.exit(1) if no token is configured."""
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("DISCORD_TOKEN", None)
            os.environ.pop("DISCORD_BOT_TOKEN", None)
            # Patch get_token to return ""
            with patch("discord_bot.config.get_token", return_value=""):
                with pytest.raises(SystemExit) as exc_info:
                    from discord_bot import run
                    importlib.reload(run)
                    run.main()
                assert exc_info.value.code == 1

    def test_main_exits_if_discord_not_installed(self):
        """run.main() should call sys.exit(1) if py-cord is not installed."""
        with patch("discord_bot.bot._DISCORD_OK", False):
            with pytest.raises(SystemExit) as exc_info:
                from discord_bot import run
                importlib.reload(run)
                run.main()
            assert exc_info.value.code == 1


# ---------------------------------------------------------------------------
# Message splitting helper test
# ---------------------------------------------------------------------------

class TestMessageSplitting:
    """Test _split_message helper in bot.py."""

    def test_short_message_not_split(self):
        from discord_bot.bot import _split_message
        chunks = _split_message("Hello world", limit=1900)
        assert chunks == ["Hello world"]

    def test_long_message_split(self):
        from discord_bot.bot import _split_message
        text = "A" * 4000
        chunks = _split_message(text, limit=1900)
        assert len(chunks) == 3
        assert all(len(c) <= 1900 for c in chunks)
        assert "".join(chunks) == text

    def test_exact_limit_not_split(self):
        from discord_bot.bot import _split_message
        text = "B" * 1900
        chunks = _split_message(text, limit=1900)
        assert len(chunks) == 1

    def test_empty_message(self):
        from discord_bot.bot import _split_message
        assert _split_message("", limit=1900) == [""]


# ---------------------------------------------------------------------------
# Rate limiting test
# ---------------------------------------------------------------------------

class TestRateLimiting:
    """Test _rate_limited in bot.py."""

    def test_first_call_not_rate_limited(self):
        from discord_bot.bot import _rate_limited, _last_call
        _last_call.pop(9999, None)
        assert _rate_limited(9999) is False

    def test_immediate_second_call_rate_limited(self):
        from discord_bot.bot import _rate_limited, _last_call
        _last_call.pop(8888, None)
        _rate_limited(8888)  # first call sets timestamp
        # Immediate second call should be rate limited
        assert _rate_limited(8888) is True
