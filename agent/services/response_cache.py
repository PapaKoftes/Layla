"""Small in-memory response cache for repeated short chat turns."""
from __future__ import annotations

import hashlib
import threading
import time
from typing import Any

_LOCK = threading.Lock()
_CACHE: dict[str, tuple[float, dict[str, Any]]] = {}
_hits = 0
_misses = 0
_puts = 0


def get_response_cache_stats() -> dict[str, Any]:
    """Hits/misses/size for response cache (observability, e.g. GET /health)."""
    with _LOCK:
        h, m, p, sz = _hits, _misses, _puts, len(_CACHE)
    total = h + m
    hit_ratio = (h / total) if total else 0.0
    return {
        "hits": h,
        "misses": m,
        "puts": p,
        "size": sz,
        "hit_ratio": round(hit_ratio, 4),
    }


def _key(message: str, aspect_id: str) -> str:
    raw = f"{(message or '').strip().lower()}::{(aspect_id or '').strip().lower()}"
    return hashlib.sha256(raw.encode("utf-8", errors="ignore")).hexdigest()


def get_cached_response(message: str, aspect_id: str, ttl_seconds: int) -> dict[str, Any] | None:
    global _hits, _misses
    if ttl_seconds <= 0:
        return None
    k = _key(message, aspect_id)
    now = time.time()
    with _LOCK:
        row = _CACHE.get(k)
        if not row:
            _misses += 1
            return None
        ts, payload = row
        if (now - ts) > float(ttl_seconds):
            _CACHE.pop(k, None)
            _misses += 1
            return None
        _hits += 1
        return dict(payload)


def put_cached_response(message: str, aspect_id: str, payload: dict[str, Any], max_entries: int = 300) -> None:
    global _puts
    if not isinstance(payload, dict) or not payload:
        return
    k = _key(message, aspect_id)
    with _LOCK:
        _puts += 1
        _CACHE[k] = (time.time(), dict(payload))
        # Keep memory bounded.
        if len(_CACHE) > max(50, int(max_entries)):
            items = sorted(_CACHE.items(), key=lambda x: x[1][0])
            trim = len(items) - max(50, int(max_entries))
            for i in range(max(0, trim)):
                _CACHE.pop(items[i][0], None)
