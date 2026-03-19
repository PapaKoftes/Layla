"""
Short-lived completion cache (prompt hash -> last non-stream response).
Opt-in via runtime_config completion_cache_enabled. Never enabled by default.

Cache key includes model name, temperature, max_tokens so different inference
parameters never collide.
"""
from __future__ import annotations

import hashlib
import json
import threading
import time
from typing import Any

_cache: dict[str, tuple[Any, float]] = {}
_lock = threading.Lock()
_cache_hits = 0
_cache_misses = 0
_DEFAULT_TTL = 45.0
_DEFAULT_MAX_ENTRIES = 500


def get_cache_stats() -> dict[str, Any]:
    """Hits/misses for non-stream completion cache lookups (observability)."""
    with _lock:
        h, m = _cache_hits, _cache_misses
        size = len(_cache)
    total = h + m
    hit_ratio = (h / total) if total else 0.0
    return {
        "hits": h,
        "misses": m,
        "size": size,
        "hit_ratio": round(hit_ratio, 4),
    }


def _ttl_seconds() -> float:
    try:
        import runtime_safety

        return float(runtime_safety.load_config().get("completion_cache_ttl_seconds", _DEFAULT_TTL))
    except Exception:
        return _DEFAULT_TTL


def _max_entries() -> int:
    try:
        import runtime_safety

        return max(10, int(runtime_safety.load_config().get("completion_cache_max_entries", _DEFAULT_MAX_ENTRIES)))
    except Exception:
        return _DEFAULT_MAX_ENTRIES


def _make_key(
    prompt: str,
    routing_tag: str,
    model_name: str,
    temperature: float,
    max_tokens: int,
) -> str:
    raw = f"{routing_tag}|{model_name}|{temperature:.3f}|{max_tokens}|{prompt}"
    return hashlib.sha256(raw.encode("utf-8", errors="replace")).hexdigest()


def get_cached(
    prompt: str,
    routing_tag: str,
    model_name: str,
    temperature: float,
    max_tokens: int,
) -> Any | None:
    """Return cached completion dict if fresh, else None."""
    key = _make_key(prompt, routing_tag, model_name, temperature, max_tokens)
    now = time.monotonic()
    ttl = _ttl_seconds()
    with _lock:
        global _cache_hits, _cache_misses
        if key not in _cache:
            _cache_misses += 1
            return None
        val, ts = _cache[key]
        if now - ts >= ttl:
            del _cache[key]
            _cache_misses += 1
            return None
        _cache_hits += 1
        return json.loads(json.dumps(val))  # shallow copy for safety


def set_cached(
    prompt: str,
    routing_tag: str,
    model_name: str,
    temperature: float,
    max_tokens: int,
    value: Any,
) -> None:
    """Store a JSON-serializable completion result."""
    if not isinstance(value, dict):
        return
    try:
        json.dumps(value)
    except (TypeError, ValueError):
        return
    key = _make_key(prompt, routing_tag, model_name, temperature, max_tokens)
    now = time.monotonic()
    cap = _max_entries()
    evict_n = max(1, cap // 10)
    with _lock:
        if len(_cache) >= cap:
            sorted_keys = sorted(_cache.keys(), key=lambda k: _cache[k][1])[:evict_n]
            for k in sorted_keys:
                _cache.pop(k, None)
        _cache[key] = (value, now)
