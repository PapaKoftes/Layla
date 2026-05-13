"""Tests for guild configuration database."""
import pytest
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

# Ensure agent is on path
_agent = Path(__file__).resolve().parent.parent.parent / "agent"
if str(_agent) not in sys.path:
    sys.path.insert(0, str(_agent))


@pytest.fixture(autouse=True)
def temp_db(tmp_path):
    """Use a temporary database for each test."""
    import discord_bot.guild_config as gc
    gc._conn = None  # Reset connection
    gc._DB_PATH = tmp_path / "test_guild_config.db"
    yield
    gc.close_db()


class TestGetConfig:
    def test_default_config(self):
        from discord_bot.guild_config import get_config
        cfg = get_config(123456)
        assert cfg["guild_id"] == 123456
        assert cfg["tts_enabled"] is True
        assert cfg["music_enabled"] is True
        assert cfg["max_response_length"] == 1900
        assert cfg["allowed_channels"] == []
        assert cfg["embed_responses"] is True

    def test_default_aspect_empty(self):
        from discord_bot.guild_config import get_config
        cfg = get_config(123456)
        assert cfg["default_aspect"] == ""


class TestSetConfig:
    def test_set_and_get(self):
        from discord_bot.guild_config import set_config, get_config
        set_config(111, default_aspect="morrigan", tts_enabled=False)
        cfg = get_config(111)
        assert cfg["default_aspect"] == "morrigan"
        assert cfg["tts_enabled"] is False

    def test_update_existing(self):
        from discord_bot.guild_config import set_config, get_config
        set_config(222, tts_enabled=True, music_enabled=True)
        set_config(222, tts_enabled=False)
        cfg = get_config(222)
        assert cfg["tts_enabled"] is False
        assert cfg["music_enabled"] is True  # unchanged

    def test_set_allowed_channels(self):
        from discord_bot.guild_config import set_config, get_config
        set_config(333, allowed_channels=[100, 200, 300])
        cfg = get_config(333)
        assert cfg["allowed_channels"] == [100, 200, 300]

    def test_set_admin_roles(self):
        from discord_bot.guild_config import set_config, get_config
        set_config(444, admin_roles=[900, 901])
        cfg = get_config(444)
        assert cfg["admin_roles"] == [900, 901]

    def test_set_max_response_length(self):
        from discord_bot.guild_config import set_config, get_config
        set_config(555, max_response_length=500)
        cfg = get_config(555)
        assert cfg["max_response_length"] == 500


class TestDeleteConfig:
    def test_delete_existing(self):
        from discord_bot.guild_config import set_config, delete_config, get_config
        set_config(666, default_aspect="nyx")
        assert delete_config(666) is True
        cfg = get_config(666)
        assert cfg["default_aspect"] == ""  # back to default

    def test_delete_nonexistent(self):
        from discord_bot.guild_config import delete_config
        assert delete_config(999) is False


class TestListGuilds:
    def test_empty(self):
        from discord_bot.guild_config import list_guilds
        assert list_guilds() == []

    def test_lists_configured(self):
        from discord_bot.guild_config import set_config, list_guilds
        set_config(100, tts_enabled=True)
        set_config(200, tts_enabled=False)
        guilds = list_guilds()
        assert set(guilds) == {100, 200}


class TestChannelAllowed:
    def test_no_restrictions(self):
        from discord_bot.guild_config import is_channel_allowed
        assert is_channel_allowed(123, 456) is True

    def test_restricted(self):
        from discord_bot.guild_config import set_config, is_channel_allowed
        set_config(123, allowed_channels=[100, 200])
        assert is_channel_allowed(123, 100) is True
        assert is_channel_allowed(123, 300) is False


class TestDefaultAspect:
    def test_no_default(self):
        from discord_bot.guild_config import get_default_aspect
        assert get_default_aspect(123) == ""

    def test_with_default(self):
        from discord_bot.guild_config import set_config, get_default_aspect
        set_config(123, default_aspect="lilith")
        assert get_default_aspect(123) == "lilith"


class TestShouldUseEmbeds:
    def test_default_true(self):
        from discord_bot.guild_config import should_use_embeds
        assert should_use_embeds(123) is True

    def test_disabled(self):
        from discord_bot.guild_config import set_config, should_use_embeds
        set_config(123, embed_responses=False)
        assert should_use_embeds(123) is False
