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

# `None` means "resolve per call" (see `_crash_dir`). Tests assign a concrete tmp Path here to
# pin it; production leaves it None so LAYLA_DATA_DIR is honoured.
CRASH_DIR: Path | None = None


def _crash_dir() -> Path:
    """`<LAYLA_DATA_DIR or ~>/.layla/crashes`.

    Was `Path.home() / ".layla" / "crashes"` evaluated at import, which ignored LAYLA_DATA_DIR
    and made `install_crash_handler()` (called from main.py's lifespan) mkdir into the operator's
    real home during the test suite. Resolved per call so import order cannot defeat it.
    """
    if CRASH_DIR is not None:
        return Path(CRASH_DIR)
    raw = (os.environ.get("LAYLA_DATA_DIR") or "").strip()
    root = Path(raw).expanduser().resolve() if raw else Path.home()
    return root / ".layla" / "crashes"


def _write_crash_dump(exc_type, exc_value, exc_tb, *, thread_name: str | None = None) -> None:
    try:
        _crash_dir().mkdir(parents=True, exist_ok=True)
        dump = {
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "exception": str(exc_value),
            "type": getattr(exc_type, "__name__", str(exc_type)),
            "thread": thread_name or "MainThread",
            "traceback": traceback.format_exception(exc_type, exc_value, exc_tb),
            "pid": os.getpid(),
        }
        path = _crash_dir() / f"crash_{int(time.time() * 1000)}.json"
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
    _crash_dir().mkdir(parents=True, exist_ok=True)
    logger.info("Crash handler installed (main + threads + faulthandler) → %s", _crash_dir())


def get_recent_crashes(limit: int = 10) -> list[dict]:
    """Return the N most recent crash dumps."""
    if not _crash_dir().exists():
        return []
    files = sorted(_crash_dir().glob("crash_*.json"), reverse=True)[:limit]
    results = []
    for f in files:
        try:
            results.append(json.loads(f.read_text(encoding="utf-8")))
        except Exception:
            continue
    return results


def clear_crashes() -> int:
    """Delete all crash dumps. Returns count deleted."""
    if not _crash_dir().exists():
        return 0
    count = 0
    for f in _crash_dir().glob("crash_*.json"):
        try:
            f.unlink()
            count += 1
        except Exception:
            pass
    return count
