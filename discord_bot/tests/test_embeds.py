"""Tests for Discord rich embed builders."""
import pytest
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

# Ensure agent is on path for any transitive imports
_agent = Path(__file__).resolve().parent.parent.parent / "agent"
if str(_agent) not in sys.path:
    sys.path.insert(0, str(_agent))


# Mock discord module if not installed
class _MockEmbed:
    """Minimal mock of discord.Embed for testing without py-cord."""
    def __init__(self, **kwargs):
        self.title = kwargs.get("title")
        self.description = kwargs.get("description")
        self.color = kwargs.get("color")
        self.url = kwargs.get("url")
        self.timestamp = kwargs.get("timestamp")
        self._footer = {}
        self._fields = []

    def set_footer(self, **kwargs):
        self._footer = kwargs
        return self

    def add_field(self, **kwargs):
        self._fields.append(kwargs)
        return self


@pytest.fixture(autouse=True)
def mock_discord_module():
    """Provide a mock discord module for testing without py-cord installed."""
    mock_discord = MagicMock()
    mock_discord.Embed = _MockEmbed
    old_discord = sys.modules.get("discord")
    sys.modules["discord"] = mock_discord
    sys.modules["discord.ext"] = MagicMock()
    sys.modules["discord.ext.commands"] = MagicMock()
    sys.modules["discord.app_commands"] = MagicMock()
    # Force reload the module to pick up mock
    if "discord_bot.rich_embeds" in sys.modules:
        del sys.modules["discord_bot.rich_embeds"]
    yield
    # Restore
    if old_discord is not None:
        sys.modules["discord"] = old_discord
    elif "discord" in sys.modules:
        del sys.modules["discord"]
    if "discord_bot.rich_embeds" in sys.modules:
        del sys.modules["discord_bot.rich_embeds"]


class TestAspectThemes:
    def test_all_aspects_have_themes(self):
        from discord_bot.rich_embeds import ASPECT_THEMES
        expected = {"morrigan", "nyx", "echo", "eris", "cassandra", "lilith"}
        assert expected == set(ASPECT_THEMES.keys())

    def test_themes_have_required_keys(self):
        from discord_bot.rich_embeds import ASPECT_THEMES
        required_keys = {"color", "icon", "title_prefix", "quote"}
        for name, theme in ASPECT_THEMES.items():
            for key in required_keys:
                assert key in theme, f"Aspect {name} missing key {key}"

    def test_colors_are_ints(self):
        from discord_bot.rich_embeds import ASPECT_THEMES
        for name, theme in ASPECT_THEMES.items():
            assert isinstance(theme["color"], int), f"Aspect {name} color should be int"
            assert 0 <= theme["color"] <= 0xFFFFFF, f"Aspect {name} color out of range"


class TestGetTheme:
    def test_known_aspect(self):
        from discord_bot.rich_embeds import _get_theme
        theme = _get_theme("morrigan")
        assert theme["title_prefix"] == "Morrigan"

    def test_unknown_aspect(self):
        from discord_bot.rich_embeds import _get_theme, DEFAULT_THEME
        theme = _get_theme("unknown_aspect")
        assert theme == DEFAULT_THEME

    def test_none_aspect(self):
        from discord_bot.rich_embeds import _get_theme, DEFAULT_THEME
        theme = _get_theme(None)
        assert theme == DEFAULT_THEME

    def test_case_insensitive(self):
        from discord_bot.rich_embeds import _get_theme
        theme = _get_theme("MORRIGAN")
        assert theme["title_prefix"] == "Morrigan"


class TestResponseEmbed:
    def test_basic_response(self):
        from discord_bot.rich_embeds import response_embed
        embed = response_embed("Hello world", aspect="nyx")
        assert embed.description == "Hello world"

    def test_long_content_truncated(self):
        from discord_bot.rich_embeds import response_embed
        long_text = "x" * 5000
        embed = response_embed(long_text)
        assert len(embed.description) <= 4000

    def test_with_metadata(self):
        from discord_bot.rich_embeds import response_embed
        embed = response_embed(
            "Test", aspect="echo",
            model="claude-3", latency_ms=150.5,
            memory_count=42, confidence=0.95,
        )
        # Should not raise
        assert embed.description == "Test"


class TestErrorEmbed:
    def test_basic_error(self):
        from discord_bot.rich_embeds import error_embed
        embed = error_embed("Test Error", "Something broke")
        assert "Test Error" in embed.title
        assert embed.description == "Something broke"

    def test_default_description(self):
        from discord_bot.rich_embeds import error_embed
        embed = error_embed()
        assert "unexpected" in embed.description.lower()


class TestStatusEmbed:
    def test_with_fields(self):
        from discord_bot.rich_embeds import status_embed
        embed = status_embed(
            "Bot Status",
            fields={"Latency": "50ms", "Guilds": "3"},
            aspect="cassandra",
        )
        assert "Bot Status" in embed.title


class TestHelpEmbed:
    def test_help_embed_created(self):
        from discord_bot.rich_embeds import help_embed
        embed = help_embed(aspect="eris")
        assert "Commands" in embed.title
