"""
Local-only telemetry: writes to layla.db telemetry_events. Gated by telemetry_enabled.
No network. Heuristic suggestions from recent events only.
"""
from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger("layla")


def log_event(
    task_type: str | None,
    reasoning_mode: str | None,
    model_used: str | None,
    latency_ms: float,
    success: bool,
    performance_mode: str | None,
) -> None:
    """Record one run if telemetry_enabled in config."""
    try:
        import runtime_safety
        from layla.memory.db import log_telemetry_event as _db_log

        cfg = runtime_safety.load_config()
        if not cfg.get("telemetry_enabled", True):
            return
        if (reasoning_mode or "").strip().lower() == "none" and not cfg.get("telemetry_log_trivial", False):
            return
        _db_log(
            task_type=task_type,
            reasoning_mode=reasoning_mode,
            model_used=model_used,
            latency_ms=float(latency_ms),
            success=1 if success else 0,
            performance_mode=performance_mode,
        )
    except Exception as e:
        logger.debug("telemetry log_event: %s", e)


def get_recent_events(n: int = 50) -> list[dict[str, Any]]:
    try:
        from layla.memory.db import get_recent_telemetry_events

        return get_recent_telemetry_events(n=n)
    except Exception as e:
        logger.debug("telemetry get_recent_events: %s", e)
        return []


def get_user_profile() -> dict[str, float]:
    """
    Analyze recent telemetry events (local DB only). Ratios are 0..1.
    Respects telemetry_enabled: when off, returns neutral ratios (no adaptation bias).
    """
    try:
        import runtime_safety

        if not runtime_safety.load_config().get("telemetry_enabled", True):
            return {"simple_ratio": 0.0, "coding_ratio": 0.0}
    except Exception:
        pass
    events = get_recent_events(50)
    n = len(events)
    if not n:
        return {"simple_ratio": 0.0, "coding_ratio": 0.0}
    simple = sum(1 for e in events if (e.get("reasoning_mode") or "").lower() == "none")
    coding = sum(1 for e in events if (e.get("reasoning_mode") or "").lower() == "deep")
    return {
        "simple_ratio": simple / n,
        "coding_ratio": coding / n,
    }


def suggest_optimization(task_type: str) -> dict[str, bool]:
    """
    Read last 50 events; return simple flags. No external calls.
    prefer_fast: many slow successful runs
    prefer_coding_model: task_type often coding-related and high latency
    """
    _ = task_type  # reserved for future weighting
    events = get_recent_events(50)
    if not events:
        return {"prefer_fast": False, "prefer_coding_model": False}

    latencies = [float(e.get("latency_ms") or 0) for e in events if e.get("latency_ms") is not None]
    successes = [e for e in events if int(e.get("success") or 0) == 1]
    avg_lat = sum(latencies) / max(len(latencies), 1)

    coding_hits = sum(
        1
        for e in events
        if (e.get("task_type") or "").lower() in ("coding", "code", "implement")
        or (e.get("reasoning_mode") or "").lower() == "deep"
    )

    prefer_fast = len(successes) >= 5 and avg_lat > 15_000
    prefer_coding_model = coding_hits >= 8 and avg_lat > 8_000

    return {"prefer_fast": prefer_fast, "prefer_coding_model": prefer_coding_model}
