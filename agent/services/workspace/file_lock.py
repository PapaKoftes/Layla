"""Process-local re-entrant locks keyed by normalized filesystem paths."""
from __future__ import annotations

import threading
from collections import defaultdict
from contextlib import contextmanager
from pathlib import Path

_guard = threading.Lock()
_locks: dict[str, threading.RLock] = defaultdict(threading.RLock)


def _key(path: str | Path) -> str:
    try:
        return str(Path(path).expanduser().resolve())
    except Exception:
        return str(path).strip()


@contextmanager
def path_lock(path: str | Path):
    """Hold an RLock for one normalized path (e.g. file being edited by a sub-agent)."""
    k = _key(path)
    lock = _locks[k]
    lock.acquire()
    try:
        yield
    finally:
        lock.release()


def clear_locks_for_tests() -> None:
    """Test helper: release registry (do not use in production)."""
    global _locks
    with _guard:
        _locks = defaultdict(threading.RLock)
