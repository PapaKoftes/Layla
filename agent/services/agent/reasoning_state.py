"""Shared cross-request reasoning-mode state.

Both the streaming (stream_handler) and non-streaming (agent_loop) paths
read/write this state so mode transitions smooth across request types.
"""
from __future__ import annotations

import threading

_last_reasoning_mode: str = ""
_reason_mode_lock = threading.Lock()


def get_lock() -> threading.Lock:
    return _reason_mode_lock


def get() -> str:
    return _last_reasoning_mode


def set_(value: str) -> None:
    global _last_reasoning_mode
    _last_reasoning_mode = value
