"""Cross-run read_file result cache (mtime + size keyed)."""

from __future__ import annotations

import json
import threading
from collections import OrderedDict
from pathlib import Path
from typing import Any


def stat_cache_key(path: Path) -> tuple[str, int, int] | None:
    """Return (resolved_str, mtime_ns, size) or None if unreadable."""
    try:
        rp = path.expanduser().resolve()
        st = rp.stat()
        return (str(rp), int(st.st_mtime_ns), int(st.st_size))
    except OSError:
        return None


def _deep_copy_jsonish(obj: dict[str, Any]) -> dict[str, Any]:
    try:
        return json.loads(json.dumps(obj, ensure_ascii=False, default=str))
    except Exception:
        return dict(obj)


class CrossRunReadCache:
    """LRU cache of read_file outputs keyed by path identity + content version (mtime, size)."""

    def __init__(self, *, max_entries: int = 512) -> None:
        self._max = max(32, int(max_entries))
        self._lock = threading.Lock()
        self._lru: OrderedDict[tuple[str, int, int], dict[str, Any]] = OrderedDict()

    def get(self, path_str: str) -> dict[str, Any] | None:
        sk = stat_cache_key(Path(path_str))
        if not sk:
            return None
        with self._lock:
            if sk not in self._lru:
                return None
            self._lru.move_to_end(sk)
            return _deep_copy_jsonish(self._lru[sk])

    def put(self, path_str: str, result: dict[str, Any]) -> None:
        if not isinstance(result, dict) or result.get("ok") is False:
            return
        sk = stat_cache_key(Path(path_str))
        if not sk:
            return
        with self._lock:
            self._lru[sk] = _deep_copy_jsonish(result)
            self._lru.move_to_end(sk)
            while len(self._lru) > self._max:
                self._lru.popitem(last=False)


_global_cache: CrossRunReadCache | None = None
_global_entry_cap = 512
_singleton_lock = threading.Lock()


def get_cross_run_read_cache(cfg: dict[str, Any] | None) -> CrossRunReadCache | None:
    """Return shared LRU cache when enabled in runtime config."""
    global _global_cache, _global_entry_cap
    c = cfg or {}
    if not bool(c.get("autonomous_read_cache_enabled", True)):
        return None
    cap = int(c.get("autonomous_read_cache_max_entries") or 512)
    if cap < 32:
        cap = 32
    with _singleton_lock:
        if _global_cache is None or cap != _global_entry_cap:
            _global_entry_cap = cap
            _global_cache = CrossRunReadCache(max_entries=cap)
        return _global_cache
