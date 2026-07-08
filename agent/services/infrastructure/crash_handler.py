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


def _write_crash_dump(exc_type, exc_value, exc_tb, *, thread_name: str | None = None) -> None:
    try:
        CRASH_DIR.mkdir(parents=True, exist_ok=True)
        dump = {
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "exception": str(exc_value),
            "type": getattr(exc_type, "__name__", str(exc_type)),
            "thread": thread_name or "MainThread",
            "traceback": traceback.format_exception(exc_type, exc_value, exc_tb),
            "pid": os.getpid(),
        }
        path = CRASH_DIR / f"crash_{int(time.time() * 1000)}.json"
        path.write_text(json.dumps(dump, indent=2), encoding="utf-8")
        logger.critical("Crash dump written: %s (thread=%s)", path, dump["thread"])
    except Exception:
        pass  # Never let the crash handler itself crash


def install_crash_handler() -> None:
    """Install global exception handlers that write crash dumps to ~/.layla/crashes/.

    Covers all three crash surfaces (audit 8a): the main thread (sys.excepthook), the many
    DAEMON threads Layla runs — scheduler jobs, drone/queen, watcher, node-sync, compaction —
    (threading.excepthook, previously a blind spot: an uncaught exception there died silently),
    and hard/native crashes (faulthandler → stderr traceback for segfaults in llama.cpp etc.).
    """
    import threading

    original_hook = sys.excepthook

    def crash_hook(exc_type, exc_value, exc_tb):
        _write_crash_dump(exc_type, exc_value, exc_tb)
        original_hook(exc_type, exc_value, exc_tb)

    def thread_crash_hook(args):
        # args: (exc_type, exc_value, exc_traceback, thread)
        if args.exc_type is SystemExit:
            return
        _write_crash_dump(
            args.exc_type, args.exc_value, args.exc_traceback,
            thread_name=getattr(args.thread, "name", "unknown"),
        )

    sys.excepthook = crash_hook
    try:
        threading.excepthook = thread_crash_hook
    except Exception:
        pass
    try:
        import faulthandler
        if not faulthandler.is_enabled():
            faulthandler.enable()
    except Exception:
        pass
    CRASH_DIR.mkdir(parents=True, exist_ok=True)
    logger.info("Crash handler installed (main + threads + faulthandler) → %s", CRASH_DIR)


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
