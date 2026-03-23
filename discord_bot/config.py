"""Load Discord bot config from env or runtime_config."""
from __future__ import annotations

import os
from pathlib import Path


def _get_bool(env_var: str, default: bool = False) -> bool:
    val = os.environ.get(env_var, "").strip().lower()
    if not val:
        return default
    return val in ("1", "true", "yes", "on")


def _get_int(env_var: str, default: int) -> int:
    val = os.environ.get(env_var, "").strip()
    if not val:
        return default
    try:
        return int(val)
    except ValueError:
        return default


def get_token() -> str:
    """Discord bot token. Env DISCORD_TOKEN or DISCORD_BOT_TOKEN or runtime_config."""
    token = os.environ.get("DISCORD_TOKEN", "").strip()
    if token:
        return token
    token = os.environ.get("DISCORD_BOT_TOKEN", "").strip()
    if token:
        return token
    try:
        agent_dir = Path(__file__).resolve().parent.parent / "agent"
        import sys
        sys.path.insert(0, str(agent_dir))
        import runtime_safety  # type: ignore[import]
        cfg = runtime_safety.load_config()
        return (cfg.get("discord_bot_token") or cfg.get("discord_token") or "").strip()
    except Exception:
        return ""


def get_agent_url() -> str:
    """Layla API base URL. Env LAYLA_BASE_URL or LAYLA_API_URL (default http://localhost:8000)."""
    url = (
        os.environ.get("LAYLA_BASE_URL", "").strip()
        or os.environ.get("LAYLA_API_URL", "").strip()
    )
    if url:
        return url.rstrip("/")
    try:
        agent_dir = Path(__file__).resolve().parent.parent / "agent"
        import sys
        sys.path.insert(0, str(agent_dir))
        import runtime_safety  # type: ignore[import]
        cfg = runtime_safety.load_config()
        url = (cfg.get("layla_api_url") or cfg.get("agent_url") or "").strip()
        if url:
            return url.rstrip("/")
    except Exception:
        pass
    return "http://localhost:8000"


def get_command_prefix() -> str:
    """Legacy prefix for prefix commands (default '!')."""
    return os.environ.get("DISCORD_COMMAND_PREFIX", "!").strip() or "!"


def get_max_response_chars() -> int:
    """Max chars per Discord message before splitting (default 1900)."""
    return _get_int("DISCORD_MAX_RESPONSE_CHARS", 1900)


def get_tts_default() -> bool:
    """Whether TTS is on by default when summoned (default False)."""
    return _get_bool("DISCORD_TTS_DEFAULT", False)


def get_music_default() -> bool:
    """Whether music is enabled by default (default True)."""
    return _get_bool("DISCORD_MUSIC_DEFAULT", True)
