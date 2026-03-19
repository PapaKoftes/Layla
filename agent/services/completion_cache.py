"""
Short-lived completion cache (prompt hash -> last non-stream response).
Opt-in via runtime_config completion_cache_enabled. Never enabled by default.
"""
from __future__ import annotations

import hashlib
import json
import threading
import time
from typing import Any

_cache: dict[str, tuple[Any, float]] = {}
_lock = threading.Lock()
_DEFAULT_TTL = 45.0


def _ttl_seconds() -> float:
    try:
        import runtime_safety

        return float(runtime_safety.load_config().get("completion_cache_ttl_seconds", _DEFAULT_TTL))
    except Exception:
        return _DEFAULT_TTL


def _make_key(prompt: str, routing_tag: str) -> str:
    raw = f"{routing_tag}|{prompt}"
    return hashlib.sha256(raw.encode("utf-8", errors="replace")).hexdigest()


def get_cached(prompt: str, routing_tag: str) -> Any | None:
    """Return cached completion dict if fresh, else None."""
    key = _make_key(prompt, routing_tag)
    now = time.monotonic()
    ttl = _ttl_seconds()
    with _lock:
        if key not in _cache:
            return None
        val, ts = _cache[key]
        if now - ts >= ttl:
            del _cache[key]
            return None
        return json.loads(json.dumps(val))  # shallow copy for safety


def set_cached(prompt: str, routing_tag: str, value: Any) -> None:
    """Store a JSON-serializable completion result."""
    if not isinstance(value, dict):
        return
    try:
        json.dumps(value)
    except (TypeError, ValueError):
        return
    key = _make_key(prompt, routing_tag)
    now = time.monotonic()
    with _lock:
        if len(_cache) > 200:
            # drop oldest ~50 entries
            sorted_keys = sorted(_cache.keys(), key=lambda k: _cache[k][1])[:50]
            for k in sorted_keys:
                _cache.pop(k, None)
        _cache[key] = (value, now)
