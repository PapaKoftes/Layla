"""
TTL LRU cache for HTTP-heavy tool results (fetch URL, search).
"""
from __future__ import annotations

import json
import threading
import time
from collections import OrderedDict
from typing import Any

_lock = threading.Lock()
_store: OrderedDict[str, tuple[float, dict[str, Any]]] = OrderedDict()


def _max_entries(cfg: dict[str, Any]) -> int:
    return max(10, int(cfg.get("http_cache_max_entries") or 200))


def get_cached(key: str, cfg: dict[str, Any]) -> dict[str, Any] | None:
    ttl = int(cfg.get("http_cache_ttl_seconds") or 0)
    if ttl <= 0:
        return None
    now = time.monotonic()
    with _lock:
        ent = _store.get(key)
        if not ent:
            return None
        exp, val = ent
        if now > exp:
            del _store[key]
            return None
        _store.move_to_end(key)
        return json.loads(json.dumps(val))


def set_cached(key: str, value: dict[str, Any], cfg: dict[str, Any]) -> None:
    ttl = int(cfg.get("http_cache_ttl_seconds") or 0)
    if ttl <= 0:
        return
    max_e = _max_entries(cfg)
    now = time.monotonic()
    exp = now + ttl
    # deep copy via json for immutability of cached snapshot
    snap = json.loads(json.dumps(value))
    with _lock:
        _store[key] = (exp, snap)
        _store.move_to_end(key)
        while len(_store) > max_e:
            _store.popitem(last=False)


def clear_cache() -> None:
    with _lock:
        _store.clear()
