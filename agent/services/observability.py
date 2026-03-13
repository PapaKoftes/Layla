"""
Structured logging for agent events.
Uses loguru when available, else standard logging.
Events include: timestamp, event_type, duration, status (per v1 spec).
"""
import logging
import time
from typing import Any

logger = logging.getLogger("layla")

try:
    from loguru import logger as _loguru
    _USE_LOGURU = True
except ImportError:
    _USE_LOGURU = False


def _log_event(event: str, **kwargs: Any) -> None:
    """Emit structured event. Ensures timestamp, event_type, duration, status."""
    from datetime import datetime
    ts = datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")
    duration = kwargs.pop("duration", kwargs.pop("duration_ms", 0))
    status = kwargs.pop("status", "ok")
    base = {"timestamp": ts, "event_type": event, "duration": duration, "status": status}
    base.update(kwargs)
    extra = " | ".join(f"{k}={v}" for k, v in sorted(base.items()) if v is not None)
    msg = f"[{event}] {extra}" if extra else f"[{event}]"
    if _USE_LOGURU:
        _loguru.bind(event=event, **base).info(msg)
    else:
        logger.info("%s %s", event, base)


def log_agent_response(aspect: str, duration_ms: float, status: str, **kw: Any) -> None:
    _log_event("agent_response", aspect=aspect, duration_ms=round(duration_ms, 2), status=status, **kw)


def log_tool_call(tool: str, duration_ms: float, status: str, **kw: Any) -> None:
    _log_event("tool_call", tool=tool, duration_ms=round(duration_ms, 2), status=status, **kw)


def log_learning_saved(content_preview: str, source: str, **kw: Any) -> None:
    _log_event("learning_saved", content_preview=content_preview[:80], source=source, **kw)


def log_learning_skipped(reason: str, **kw: Any) -> None:
    _log_event("learning_skipped", reason=reason, **kw)


def log_study_started(topic: str, **kw: Any) -> None:
    _log_event("study_started", topic=topic, **kw)


def log_study_completed(topic: str, duration_ms: float, **kw: Any) -> None:
    _log_event("study_completed", topic=topic, duration_ms=round(duration_ms, 2), **kw)


def log_memory_retrieval(query_preview: str, hits: int, **kw: Any) -> None:
    _log_event("memory_retrieval", query_preview=query_preview[:60], hits=hits, **kw)


def log_agent_plan_created(steps: int, goal_preview: str = "", **kw: Any) -> None:
    _log_event("agent_plan_created", steps=steps, goal_preview=goal_preview[:60], **kw)


def log_agent_plan_step(step: int, task: str, status: str, **kw: Any) -> None:
    _log_event("agent_plan_step", step=step, task=task[:80], status=status, **kw)


def log_agent_plan_completed(steps: int, **kw: Any) -> None:
    _log_event("agent_plan_completed", steps=steps, **kw)


def log_retrieval_results(query_preview: str, count: int, **kw: Any) -> None:
    _log_event("retrieval_results", query_preview=query_preview[:60], count=count, **kw)


def log_tool_result(tool: str, ok: bool, duration_ms: float = 0, **kw: Any) -> None:
    _log_event("tool_result", tool=tool, ok=ok, duration_ms=round(duration_ms, 2), **kw)


def log_planner_invoked(steps: int = 0, goal_preview: str = "", duration_ms: float = 0, **kw: Any) -> None:
    _log_event("planner_invoked", steps=steps, goal_preview=goal_preview[:60], duration=duration_ms, **kw)


def log_agent_started(**kw: Any) -> None:
    _log_event("agent_started", **kw)


def log_agent_shutdown(duration_ms: float = 0, **kw: Any) -> None:
    _log_event("agent_shutdown", duration=duration_ms, **kw)


def log_retrieval_cache_hit(query_preview: str = "", duration_ms: float = 0, **kw: Any) -> None:
    _log_event("retrieval_cache_hit", query_preview=query_preview[:60], duration=duration_ms, **kw)


def log_retrieval_cache_miss(query_preview: str = "", duration_ms: float = 0, **kw: Any) -> None:
    _log_event("retrieval_cache_miss", query_preview=query_preview[:60], duration=duration_ms, **kw)
