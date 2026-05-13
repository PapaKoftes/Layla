"""
Global exception handler that writes crash dumps to ~/.layla/crashes/.

Crash dumps are JSON files containing traceback, timestamp, and metadata.
Safe to import without side effects -- call install_crash_handler() explicitly.
"""
from __future__ import annotations

import json
import logging
import os
import sys
import time
import traceback
from pathlib import Path

logger = logging.getLogger("layla")

CRASH_DIR = Path.home() / ".layla" / "crashes"


def install_crash_handler() -> None:
    """Install global exception handler that writes crash dumps to ~/.layla/crashes/."""
    original_hook = sys.excepthook

    def crash_hook(exc_type, exc_value, exc_tb):
        try:
            CRASH_DIR.mkdir(parents=True, exist_ok=True)
            dump = {
                "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                "exception": str(exc_value),
                "type": exc_type.__name__,
                "traceback": traceback.format_exception(exc_type, exc_value, exc_tb),
                "pid": os.getpid(),
            }
            path = CRASH_DIR / f"crash_{int(time.time())}.json"
            path.write_text(json.dumps(dump, indent=2), encoding="utf-8")
            logger.critical("Crash dump written: %s", path)
        except Exception:
            pass  # Never let the crash handler itself crash
        original_hook(exc_type, exc_value, exc_tb)

    sys.excepthook = crash_hook
    CRASH_DIR.mkdir(parents=True, exist_ok=True)
    logger.info("Crash handler installed → %s", CRASH_DIR)


def get_recent_crashes(limit: int = 10) -> list[dict]:
    """Return the N most recent crash dumps."""
    if not CRASH_DIR.exists():
        return []
    files = sorted(CRASH_DIR.glob("crash_*.json"), reverse=True)[:limit]
    results = []
    for f in files:
        try:
            results.append(json.loads(f.read_text(encoding="utf-8")))
        except Exception:
            continue
    return results


def clear_crashes() -> int:
    """Delete all crash dumps. Returns count deleted."""
    if not CRASH_DIR.exists():
        return 0
    count = 0
    for f in CRASH_DIR.glob("crash_*.json"):
        try:
            f.unlink()
            count += 1
        except Exception:
            pass
    return count
