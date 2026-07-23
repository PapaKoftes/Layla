"""
Structured logging for agent events.
Uses loguru when available, else standard logging.
Events include: timestamp, event_type, duration, status (per v1 spec).
Also records to performance_monitor for system_optimizer metrics.

NOTE (BL-010): "_legacy" here means the pre-split module layout, NOT dead code. The
`log_*` helpers below are re-exported by `services/observability/__init__.py` and remain
in active use (~7 call sites: planner, missions, learnings, run-setup). Do not delete —
retained deliberately, not superseded.
"""
import contextlib
import logging
import threading
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
        from services.observability.performance_monitor import record
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
    # Feed the structured-event ring the /metrics endpoint reads. Without this, event_logger.log_event
    # was never called in production, so /metrics observability.recent_events was permanently []. Every
    # log_* call here now also lands in that ring (best-effort — never breaks the log path).
    try:
        from services.observability.event_logger import log_event as _ring_log
        _ring_log(event, {k: v for k, v in base.items() if k not in ("timestamp", "event_type")}, level=status if status in ("info", "warning", "error") else "info")
    except Exception:
        pass
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
        from services.observability.trace_export import maybe_emit_run_budget_span

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


_tool_source = threading.local()
TOOL_SOURCE_AGENT = "agent_loop"


@contextlib.contextmanager
def tool_invocation_source(source: str):
    """Mark who is invoking tools on this thread, so reliability stats know their own provenance.

    tool_outcomes is written by a wrapper installed over EVERY entry in TOOLS
    (layla/tools/registry.py), so it fires for any invoker: the agent loop, direct TOOLS[...] calls,
    approvals, the ingestion pipeline, skill packs, and capability self-test sweeps. It recorded no
    provenance at all — every row landed with context='' — so those populations were indistinguishable.

    That was not harmless bookkeeping. rl_feedback.compute_tool_preferences builds the planner's
    "prefer"/"avoid" hints from get_tool_reliability(), which aggregated the lot. On the operator's box
    a single minute (2026-07-16T16:29) contributed 132 rows in which ~150 DISTINCT tools each ran
    exactly once — a registry enumeration, not conversation — and the disk-touching tools all failed
    against an empty sandbox_root. The planner therefore learned to AVOID read_file, file_info and
    list_dir from a self-test artifact rather than from experience.
    """
    prev = getattr(_tool_source, "value", "")
    _tool_source.value = source
    try:
        yield
    finally:
        _tool_source.value = prev


def current_tool_source() -> str:
    return getattr(_tool_source, "value", "") or ""


def log_tool_result(tool: str, ok: bool, duration_ms: float = 0, **kw: Any) -> None:
    _log_event("tool_result", tool=tool, ok=ok, duration_ms=round(duration_ms, 2), **kw)
    if duration_ms > 0:
        _record_to_performance_monitor("tool_latency_ms", duration_ms, {"tool": tool})
    # Liveness (CP-3): this is the UNIVERSAL tool choke point — the registry wrapper calls it for
    # every TOOLS[name]["fn"] invocation, on every dispatch path. CP-3's first live run proved the
    # point: instrumenting core.executor.run_tool missed read_file entirely, because file handlers
    # dispatch through tool_dispatch._handle_read_file, not the executor. This site sees them all.
    from services.observability import liveness
    liveness.fire("tool_executed")
    # Tool outcome learning: record for reliability
    try:
        from layla.memory.db import record_tool_outcome
        # Explicit context wins; otherwise stamp the thread's invocation source so a row can be
        # attributed later. Rows written outside any marked source stay unattributed by design —
        # get_tool_reliability excludes them rather than guessing.
        context = (kw.get("context") or kw.get("goal_preview") or current_tool_source() or "")[:500]
        quality = 1.0 if ok else 0.0
        record_tool_outcome(tool, ok, context=context, latency_ms=duration_ms, quality_score=quality)
    except Exception:
        pass


def tool_health_snapshot(*, slow_ms: float = 8000.0, min_samples: int = 8) -> dict[str, Any]:
    """
    Deterministic aggregation used by policy/routing:
    - slow tools (avg latency above threshold)
    - unreliable tools (success rate below 0.35 with enough samples)
    - recent failure clusters by tool name
    """
    out: dict[str, Any] = {"slow_tools": [], "unreliable_tools": [], "failure_clusters": {}}
    try:
        from layla.memory.db import get_recent_tool_outcome_failures, get_tool_reliability

        stats = get_tool_reliability()
        slow = []
        bad = []
        for name, s in (stats or {}).items():
            try:
                cnt = int(s.get("count") or 0)
                if cnt < int(min_samples):
                    continue
                sr = float(s.get("success_rate") or 0.0)
                lat = float(s.get("avg_latency") or 0.0)
                if lat >= float(slow_ms):
                    slow.append({"tool": name, "avg_latency_ms": lat, "count": cnt})
                if sr < 0.35:
                    bad.append({"tool": name, "success_rate": sr, "count": cnt})
            except Exception:
                continue
        out["slow_tools"] = sorted(slow, key=lambda r: float(r.get("avg_latency_ms") or 0), reverse=True)[:10]
        out["unreliable_tools"] = sorted(bad, key=lambda r: float(r.get("success_rate") or 0))[:10]
        fails = get_recent_tool_outcome_failures(30)
        clusters: dict[str, int] = {}
        for r in fails:
            tn = str(r.get("tool_name") or "").strip() or "unknown"
            clusters[tn] = clusters.get(tn, 0) + 1
        out["failure_clusters"] = dict(sorted(clusters.items(), key=lambda kv: kv[1], reverse=True)[:10])
    except Exception:
        pass
    return out


def log_planner_invoked(steps: int = 0, goal_preview: str = "", duration_ms: float = 0, **kw: Any) -> None:
    _log_event("planner_invoked", steps=steps, goal_preview=goal_preview[:60], duration=duration_ms, **kw)


def log_agent_started(**kw: Any) -> None:
    _log_event("agent_started", **kw)


def log_agent_shutdown(duration_ms: float = 0, **kw: Any) -> None:
    _log_event("agent_shutdown", duration=duration_ms, **kw)


def log_execution_trace(state_summary: dict[str, Any], **kw: Any) -> None:
    """Structured execution trace (steps, pipeline, tools) for ops / debug endpoints."""
    steps = state_summary.get("steps") if isinstance(state_summary, dict) else None
    n_steps = len(steps) if isinstance(steps, list) else 0
    _log_event(
        "execution_trace",
        execution_id=str((state_summary or {}).get("execution_id") or ""),
        status=str((state_summary or {}).get("status") or ""),
        pipeline_stage=str((state_summary or {}).get("pipeline_stage") or ""),
        tool_calls=int((state_summary or {}).get("tool_calls") or 0),
        steps_n=n_steps,
        **kw,
    )


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
