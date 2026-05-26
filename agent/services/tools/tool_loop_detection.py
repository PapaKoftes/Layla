"""
Detect repetitive tool-call patterns (OpenClaw-style loop detection).
"""
from __future__ import annotations

import json
import logging
from collections import deque
from typing import Any

logger = logging.getLogger("layla")


def _signature(intent: str, decision: dict[str, Any] | None) -> str:
    args = (decision or {}).get("args") or {}
    try:
        return json.dumps(args, sort_keys=True, default=str)[:800]
    except Exception:
        return str(args)[:800]


def _consecutive_repeat_tail(history: list[tuple[str, str]]) -> int:
    if not history:
        return 0
    last_t, last_s = history[-1]
    n = 0
    for t, s in reversed(history):
        if t == last_t and s == last_s:
            n += 1
        else:
            break
    return n


def _pingpong_tail(history: list[tuple[str, str]], min_len: int = 6) -> bool:
    if len(history) < min_len:
        return False
    tail = history[-min_len:]
    tools = [t for t, _ in tail]
    if len(set(tools)) != 2:
        return False
    a, b = tools[0], tools[1]
    if a == b:
        return False
    for i, t in enumerate(tools):
        if i % 2 == 0 and t != a:
            return False
        if i % 2 == 1 and t != b:
            return False
    sigs = [s for _, s in tail]
    if len(set(sigs[0::2])) > 1 or len(set(sigs[1::2])) > 1:
        return False
    return True


def ensure_history_deque(state: dict[str, Any], maxlen: int) -> deque[tuple[str, str]]:
    h = state.get("tool_loop_history")
    if isinstance(h, deque) and h.maxlen == maxlen:
        return h
    d: deque[tuple[str, str]] = deque(h or [], maxlen=maxlen)
    state["tool_loop_history"] = d
    return d


def exact_call_key(intent: str, decision: dict[str, Any] | None) -> str:
    """Stable key for per-run exact duplicate tool invocation detection."""
    return f"{intent}\x00{_signature(intent, decision)}"


def push_and_evaluate(
    cfg: dict[str, Any],
    state: dict[str, Any],
    intent: str,
    decision: dict[str, Any] | None,
    reasoning_mode: str | None = None,
) -> str | None:
    """
    Record intended tool invocation; return None, 'WARN:...', or 'STOP:...'.
    On STOP, undo the append so the failed tool is not counted in history.
    """
    if not cfg.get("tool_loop_detection_enabled"):
        return None
    if intent in ("reason", "finish", "wakeup"):
        return None

    maxlen = int(cfg.get("tool_loop_history_size") or 30)
    hist = ensure_history_deque(state, maxlen)
    sig = _signature(intent, decision)
    was_full = len(hist) == hist.maxlen
    evicted = hist[0] if was_full else None
    hist.append((intent, sig))
    history_list = list(hist)

    warn_th = int(cfg.get("tool_loop_warning_threshold") or 10)
    stop_th = int(cfg.get("tool_loop_stop_threshold") or 20)
    rm = (reasoning_mode or "").strip().lower()
    # Default threshold 20 → effective 5 for low-reasoning modes unless operator overrides.
    if rm in ("none", "light") and stop_th == 20:
        stop_th = 5

    if cfg.get("tool_loop_detect_repeat", True):
        rep = _consecutive_repeat_tail(history_list)
        if rep >= stop_th:
            hist.pop()
            if was_full and evicted is not None:
                hist.appendleft(evicted)
            logger.warning("tool_loop_detection: blocked (repeat %s x %s)", intent, rep)
            return f"STOP:Repeated identical {intent} {rep} times. Reply with reason or change approach."
        if rep >= warn_th:
            return f"WARN:Same tool {intent} repeated {rep} times; try a different approach."

    if cfg.get("tool_loop_detect_pingpong", True) and _pingpong_tail(history_list, 6):
        # Measure the actual alternating tail length by extending in steps of 2.
        # Compare the tail length directly against warn/stop thresholds, same as repeat detection.
        pp_len = 6
        while pp_len + 2 <= len(history_list) and _pingpong_tail(history_list, pp_len + 2):
            pp_len += 2
        if pp_len >= stop_th:
            hist.pop()
            if was_full and evicted is not None:
                hist.appendleft(evicted)
            return "STOP:Ping-pong tool pattern; stop and answer or reframe."
        if pp_len >= warn_th:
            return "WARN:Alternating tools with no progress."

    return None


def consume_prompt_hint(state: dict[str, Any]) -> str:
    h = state.pop("tool_loop_prompt_hint", "") or ""
    return h
