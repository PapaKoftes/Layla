"""
Structured logging for agent events.
Uses loguru when available, else standard logging.
Events include: timestamp, event_type, duration, status (per v1 spec).
Also records to performance_monitor for system_optimizer metrics.
"""
import logging
from typing import Any

logger = logging.getLogger("layla")

try:
    from loguru import logger as _loguru
    _USE_LOGURU = True
except ImportError:
    _USE_LOGURU = False


def _record_to_performance_monitor(metric: str, value: float, tags: dict[str, str] | None = None) -> None:
    """Record metric to performance_monitor for system_optimizer to consume."""
    try:
        from services.performance_monitor import record
        record(metric, value, tags or {})
    except Exception:
        pass


def _log_event(event: str, **kwargs: Any) -> None:
    """Emit structured event. Ensures timestamp, event_type, duration, status."""
    from layla.time_utils import utcnow
    ts = utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")
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


def log_run_budget_summary(**kw: Any) -> None:
    """Single structured line per run: wall time, token estimates, tool counts, pipeline variant."""
    _log_event("run_budget_summary", **kw)
    try:
        import runtime_safety

        _cfg = runtime_safety.load_config()
        from services.langfuse_export import maybe_emit_run_budget_span

        maybe_emit_run_budget_span(_cfg, kw)
    except Exception:
        pass


def log_tool_call(tool: str, duration_ms: float, status: str, **kw: Any) -> None:
    _log_event("tool_call", tool=tool, duration_ms=round(duration_ms, 2), status=status, **kw)
    if duration_ms > 0:
        _record_to_performance_monitor("tool_latency_ms", duration_ms, {"tool": tool})


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


def log_retrieval_results(query_preview: str, count: int, duration_ms: float = 0, **kw: Any) -> None:
    _log_event("retrieval_results", query_preview=query_preview[:60], count=count, duration_ms=round(duration_ms, 2), **kw)
    if duration_ms > 0:
        _record_to_performance_monitor("retrieval_latency_ms", duration_ms, {"source": "vector"})


def log_prompt_assembled(total_tokens: int = 0, sections: int = 0, truncated: int = 0, **kw: Any) -> None:
    _log_event("prompt_assembled", total_tokens=total_tokens, sections=sections, truncated=truncated, **kw)


def log_tool_result(tool: str, ok: bool, duration_ms: float = 0, **kw: Any) -> None:
    _log_event("tool_result", tool=tool, ok=ok, duration_ms=round(duration_ms, 2), **kw)
    if duration_ms > 0:
        _record_to_performance_monitor("tool_latency_ms", duration_ms, {"tool": tool})
    # Tool outcome learning: record for reliability
    try:
        from layla.memory.db import record_tool_outcome
        context = (kw.get("context") or kw.get("goal_preview") or "")[:500]
        quality = 1.0 if ok else 0.0
        record_tool_outcome(tool, ok, context=context, latency_ms=duration_ms, quality_score=quality)
    except Exception:
        pass


def log_planner_invoked(steps: int = 0, goal_preview: str = "", duration_ms: float = 0, **kw: Any) -> None:
    _log_event("planner_invoked", steps=steps, goal_preview=goal_preview[:60], duration=duration_ms, **kw)


def log_agent_started(**kw: Any) -> None:
    _log_event("agent_started", **kw)


def log_agent_shutdown(duration_ms: float = 0, **kw: Any) -> None:
    _log_event("agent_shutdown", duration=duration_ms, **kw)


def log_retrieval_cache_hit(query_preview: str = "", duration_ms: float = 0, **kw: Any) -> None:
    _log_event("retrieval_cache_hit", query_preview=query_preview[:60], duration=duration_ms, **kw)
    if duration_ms > 0:
        _record_to_performance_monitor("retrieval_latency_ms", duration_ms, {"source": "cache_hit"})


def log_retrieval_cache_miss(query_preview: str = "", duration_ms: float = 0, **kw: Any) -> None:
    _log_event("retrieval_cache_miss", query_preview=query_preview[:60], duration_ms=duration_ms, **kw)
    if duration_ms > 0:
        _record_to_performance_monitor("retrieval_latency_ms", duration_ms, {"source": "cache_miss"})


def log_agent_decision(duration_ms: float = 0, **kw: Any) -> None:
    """Log agent decision (LLM) latency. Structured event for observability."""
    _log_event("agent_decision", duration_ms=round(duration_ms, 2), **kw)
    if duration_ms > 0:
        _record_to_performance_monitor("agent_decision_ms", duration_ms, {})


# Mission lifecycle (v1.1)
def log_mission_created(mission_id: str = "", goal_preview: str = "", steps: int = 0, **kw: Any) -> None:
    _log_event("mission_created", mission_id=mission_id, goal_preview=goal_preview[:60], steps=steps, **kw)


def log_mission_started(mission_id: str = "", goal_preview: str = "", **kw: Any) -> None:
    _log_event("mission_started", mission_id=mission_id, goal_preview=goal_preview[:60], **kw)


def log_mission_step(
    mission_id: str = "", step: int = 0, task_preview: str = "", status: str = "", duration_ms: float = 0, **kw: Any
) -> None:
    _log_event("mission_step", mission_id=mission_id, step=step, task_preview=task_preview[:60], status=status, duration_ms=duration_ms, **kw)


def log_mission_completed(mission_id: str = "", steps_done: int = 0, **kw: Any) -> None:
    _log_event("mission_completed", mission_id=mission_id, steps_done=steps_done, **kw)


def log_mission_failed(mission_id: str = "", reason: str = "", **kw: Any) -> None:
    _log_event("mission_failed", mission_id=mission_id, reason=reason[:120], **kw)
