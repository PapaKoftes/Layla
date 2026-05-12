"""Track silently-degraded subsystems for /health visibility."""
import threading

_lock = threading.Lock()
_modes: dict[str, dict] = {}


def mark_degraded(subsystem: str, reason: str) -> None:
    """Record that a subsystem fell back to a degraded path."""
    with _lock:
        entry = _modes.setdefault(subsystem, {"count": 0, "last_reason": ""})
        entry["count"] += 1
        entry["last_reason"] = str(reason)[:200]


def get_degraded() -> dict:
    """Return a snapshot of degraded subsystems."""
    with _lock:
        return {k: dict(v) for k, v in _modes.items()}


def clear() -> None:
    with _lock:
        _modes.clear()
