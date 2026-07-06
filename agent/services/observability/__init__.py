"""Observability primitives: tracing, metrics, and structured event logging.

Also re-exports all functions from the legacy observability module for backward
compatibility (services.observability was originally a single file).
"""
from __future__ import annotations

# Legacy re-exports — all existing callers of `from services.observability import X` continue to work
from services.observability._legacy_observability import (  # noqa: F401
    log_agent_decision,
    log_agent_plan_completed,
    log_agent_plan_created,
    log_agent_plan_step,
    log_agent_response,
    log_agent_shutdown,
    log_agent_started,
    log_execution_trace,
    log_learning_saved,
    log_learning_skipped,
    log_memory_retrieval,
    log_mission_completed,
    log_mission_created,
    log_mission_failed,
    log_mission_started,
    log_mission_step,
    log_planner_invoked,
    log_prompt_assembled,
    log_retrieval_cache_hit,
    log_retrieval_cache_miss,
    log_retrieval_results,
    log_run_budget_summary,
    log_study_completed,
    log_study_started,
    log_tool_call,
    log_tool_result,
    tool_health_snapshot,
)

# New observability primitives
from services.observability.event_logger import get_recent_events, log_event
from services.observability.metrics import MetricsCollector, metrics
from services.observability.security_audit import (
    get_recent_security_events,
    get_security_summary,
    log_action_denied,
    log_approval_escalation,
    log_dangerous_tool_usage,
    log_policy_bypass_attempt,
    log_protected_file_attempt,
    log_sandbox_violation,
)
from services.observability.tracing import (
    CorrelationContext,
    generate_correlation_id,
    get_current_correlation_id,
    trace_request,
)

__all__ = [
    # New
    "CorrelationContext",
    "MetricsCollector",
    "generate_correlation_id",
    "get_current_correlation_id",
    "get_recent_events",
    "get_recent_security_events",
    "get_security_summary",
    "log_action_denied",
    "log_approval_escalation",
    "log_dangerous_tool_usage",
    "log_event",
    "log_policy_bypass_attempt",
    "log_protected_file_attempt",
    "log_sandbox_violation",
    "metrics",
    "trace_request",
    # Legacy
    "log_agent_decision",
    "log_agent_plan_completed",
    "log_agent_plan_created",
    "log_agent_plan_step",
    "log_agent_response",
    "log_agent_shutdown",
    "log_agent_started",
    "log_execution_trace",
    "log_learning_saved",
    "log_learning_skipped",
    "log_memory_retrieval",
    "log_mission_completed",
    "log_mission_created",
    "log_mission_failed",
    "log_mission_started",
    "log_mission_step",
    "log_planner_invoked",
    "log_prompt_assembled",
    "log_retrieval_cache_hit",
    "log_retrieval_cache_miss",
    "log_retrieval_results",
    "log_run_budget_summary",
    "log_study_completed",
    "log_study_started",
    "log_tool_call",
    "log_tool_result",
    "tool_health_snapshot",
]
