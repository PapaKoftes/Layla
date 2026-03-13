"""
Short-lived retrieval cache. TTL 60 seconds, keyed by hash(query).
Uses functools.lru_cache if diskcache unavailable (for single-process deployments).
"""
import hashlib
import threading
import time
from typing import Any, Callable

_USE_DISKCACHE = False
try:
    import diskcache
    _USE_DISKCACHE = True
except ImportError:
    pass

_CACHE_TTL = 60.0
_cache: dict[str, tuple[Any, float]] = {}
_cache_lock = threading.Lock()


def _cache_key(query: str) -> str:
    return hashlib.sha256(query.encode("utf-8", errors="replace")).hexdigest()


def cached_retrieve(query: str, k: int, fetcher: Callable[[str, int], Any]) -> Any:
    """Call fetcher(query, k) with cache. TTL 60s. Key = hash(query|k)."""
    key = _cache_key(f"{query}|{k}")
    now = time.monotonic()
    preview = (query or "")[:60]
    with _cache_lock:
        if key in _cache:
            val, ts = _cache[key]
            if now - ts < _CACHE_TTL:
                try:
                    from services.observability import log_retrieval_cache_hit
                    log_retrieval_cache_hit(query_preview=preview, duration_ms=0)
                except Exception:
                    pass
                return val
        t0 = time.monotonic()
        result = fetcher(query, k)
        elapsed_ms = (time.monotonic() - t0) * 1000
        _cache[key] = (result, now)
        try:
            from services.observability import log_retrieval_cache_miss
            log_retrieval_cache_miss(query_preview=preview, duration_ms=elapsed_ms)
        except Exception:
            pass
        return result
