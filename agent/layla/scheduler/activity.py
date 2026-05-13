"""Activity-window helpers for the Layla scheduler.

Extracted from main.py so scheduler jobs and tests can import
without pulling in the full FastAPI application.
"""

import logging
import time

logger = logging.getLogger("layla")

# Process names (lowercase) that cause study job to skip so we don't override you
SCHEDULER_SKIP_PROCESSES = frozenset({
    "overwatch", "valorant", "steam", "fortniteclient", "riotclient",
    "league of legends", "dota 2", "elden ring", "eldenring", "hogwarts", "cyberpunk",
    "game", "games", "ea", "origin", "ubisoft", "battle.net", "epicgames",
})

# Initialized to startup time so scheduled study can run from first boot,
# not just after first message.
_last_activity_ts: float = time.time()


def record_activity() -> None:
    """Mark recent user activity for the scheduler (called from /agent, /wakeup, etc.)."""
    global _last_activity_ts
    _last_activity_ts = time.time()


def get_last_activity_ts() -> float:
    """Return the epoch timestamp of the last recorded activity."""
    return _last_activity_ts


def is_active_window(max_idle_minutes: int = 1440) -> bool:
    """True if the last user interaction was within *max_idle_minutes*."""
    return time.time() - _last_activity_ts <= max_idle_minutes * 60


def is_game_running() -> bool:
    """True if a known game / fullscreen process is running so we skip scheduled study."""
    try:
        import psutil
        for p in psutil.process_iter(["name"]):
            try:
                name = (p.info.get("name") or "").lower()
                if any(skip in name for skip in SCHEDULER_SKIP_PROCESSES):
                    return True
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
    except Exception:
        pass
    return False
