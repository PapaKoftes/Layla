"""Load Discord bot config from env or runtime_config."""
from __future__ import annotations

import os
from pathlib import Path


def get_token() -> str:
    """Discord bot token. Env DISCORD_BOT_TOKEN or runtime_config."""
    token = os.environ.get("DISCORD_BOT_TOKEN", "")
    if token:
        return token
    try:
        agent_dir = Path(__file__).resolve().parent.parent / "agent"
        import sys
        sys.path.insert(0, str(agent_dir))
        import runtime_safety
        cfg = runtime_safety.load_config()
        return cfg.get("discord_bot_token", "") or ""
    except Exception:
        return ""


def get_agent_url() -> str:
    """Layla API base URL."""
    return os.environ.get("LAYLA_API_URL", "http://127.0.0.1:8000")
