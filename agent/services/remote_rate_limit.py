"""Sliding-window rate limit for non-localhost clients when remote access is enabled.

Uses in-process memory (single-server). For multi-worker deployments, use a shared store.
"""
from __future__ import annotations

import time
from collections import deque
from threading import Lock
from typing import Deque, Dict

_window_sec = 60.0
_buckets: Dict[str, Deque[float]] = {}
_lock = Lock()


def check_rate_limit(client_key: str, max_per_minute: int) -> tuple[bool, str]:
    """
    Returns (allowed, reason_if_blocked).
    """
    if max_per_minute <= 0:
        return True, ""
    key = (client_key or "unknown").strip() or "unknown"
    now = time.monotonic()
    with _lock:
        dq = _buckets.get(key)
        if dq is None:
            dq = deque()
            _buckets[key] = dq
        cutoff = now - _window_sec
        while dq and dq[0] < cutoff:
            dq.popleft()
        if len(dq) >= max_per_minute:
            return False, "rate_limited"
        dq.append(now)
    return True, ""
