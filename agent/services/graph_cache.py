"""
Cache for graph expansion results.
Avoids repeating expensive BFS expansions for the same query.
Cache key: hash(query)
Cache value: expanded graph nodes
TTL: 300 seconds
"""
from __future__ import annotations

import hashlib
import logging
import threading
import time
from typing import Any, Callable

logger = logging.getLogger("layla")

_CACHE_TTL = 300.0
_cache: dict[str, tuple[list[dict[str, Any]], float]] = {}
_lock = threading.Lock()


def _cache_key(query: str) -> str:
    return hashlib.sha256((query or "").encode("utf-8", errors="replace")).hexdigest()


def get_cached(query: str) -> list[dict[str, Any]] | None:
    """Return cached expansion if valid, else None."""
    key = _cache_key(query)
    now = time.monotonic()
    with _lock:
        if key in _cache:
            nodes, ts = _cache[key]
            if now - ts < _CACHE_TTL:
                return nodes
            del _cache[key]
    return None


def set_cached(query: str, nodes: list[dict[str, Any]]) -> None:
    """Store expansion in cache."""
    key = _cache_key(query)
    now = time.monotonic()
    with _lock:
        _cache[key] = (nodes, now)


def cached_expand(query: str, expand_fn: Callable[..., list[dict[str, Any]]], *args: Any, **kwargs: Any) -> list[dict[str, Any]]:
    """
    Call expand_fn(query, *args, **kwargs) with cache.
    Returns cached result if valid, else computes and caches.
    """
    cached = get_cached(query)
    if cached is not None:
        return cached
    result = expand_fn(query, *args, **kwargs)
    set_cached(query, result)
    return result
