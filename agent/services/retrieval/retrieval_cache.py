"""
Short-lived retrieval cache. TTL ~60 s, keyed by hash(query|k).

Bounded LRU over an OrderedDict: without a cap this was a plain dict that grew one
permanent entry per distinct retrieval query for the whole process lifetime (each holding
a full result list) — hundreds of MB over a year of RAG use. Now capped to
retrieval_cache_max_entries with least-recently-used eviction.
"""
import hashlib
import threading
import time
from collections import OrderedDict
from typing import Any, Callable

_DEFAULT_TTL = 60.0
_DEFAULT_MAX_ENTRIES = 500
_cache: "OrderedDict[str, tuple[Any, float]]" = OrderedDict()
_cache_lock = threading.Lock()


def _get_cache_ttl() -> float:
    """TTL from runtime_config.retrieval_cache_ttl_seconds or default 60."""
    try:
        import runtime_safety
        return float(runtime_safety.load_config().get("retrieval_cache_ttl_seconds", _DEFAULT_TTL))
    except Exception:
        return _DEFAULT_TTL


def _get_max_entries() -> int:
    try:
        import runtime_safety
        return int(runtime_safety.load_config().get("retrieval_cache_max_entries", _DEFAULT_MAX_ENTRIES))
    except Exception:
        return _DEFAULT_MAX_ENTRIES


def _cache_key(query: str) -> str:
    return hashlib.sha256(query.encode("utf-8", errors="replace")).hexdigest()


def cached_retrieve(query: str, k: int, fetcher: Callable[[str, int], Any]) -> Any:
    """Call fetcher(query, k) with cache. TTL 60s. Key = hash(query|k)."""
    key = _cache_key(f"{query}|{k}")
    now = time.monotonic()
    preview = (query or "")[:60]
    ttl = _get_cache_ttl()
    with _cache_lock:
        if key in _cache:
            val, ts = _cache[key]
            if now - ts < ttl:
                _cache.move_to_end(key)  # LRU: mark most-recently-used
                try:
                    from services.observability import log_retrieval_cache_hit
                    log_retrieval_cache_hit(query_preview=preview, duration_ms=0)
                except Exception:
                    pass
                return val
            else:
                del _cache[key]  # expired — drop instead of overwriting-in-place
        t0 = time.monotonic()
        result = fetcher(query, k)
        elapsed_ms = (time.monotonic() - t0) * 1000
        _cache[key] = (result, now)
        _cache.move_to_end(key)
        # Bound the cache: evict least-recently-used entries beyond the cap.
        _max = _get_max_entries()
        while _max > 0 and len(_cache) > _max:
            _cache.popitem(last=False)
        try:
            from services.observability import log_retrieval_cache_miss
            log_retrieval_cache_miss(query_preview=preview, duration_ms=elapsed_ms)
        except Exception:
            pass
        return result
