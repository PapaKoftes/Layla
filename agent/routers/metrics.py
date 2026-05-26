"""
Metrics router -- Prometheus scrape endpoint and human-readable summary.
"""
from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import JSONResponse, PlainTextResponse

router = APIRouter(tags=["metrics"])


@router.get("/metrics")
def get_metrics():
    """Prometheus scrape endpoint. Returns text/plain if prometheus_client is available, else JSON."""
    from services.metrics import PROMETHEUS_AVAILABLE, generate_metrics_text

    if PROMETHEUS_AVAILABLE:
        return PlainTextResponse(
            generate_metrics_text(),
            media_type="text/plain; version=0.0.4; charset=utf-8",
        )
    return JSONResponse(generate_metrics_text())


@router.get("/metrics/summary")
def get_metrics_summary():
    """Human-readable metrics summary."""
    from services.metrics import get_metrics_summary

    return get_metrics_summary()


@router.get("/metrics/security")
def get_security_audit():
    """Security audit events: recent security-sensitive actions and summary."""
    try:
        from services.observability.security_audit import get_recent_security_events, get_security_summary

        return {
            "summary": get_security_summary(),
            "recent_events": get_recent_security_events(limit=50),
        }
    except Exception as exc:
        return {"error": str(exc), "summary": {}, "recent_events": []}


@router.get("/metrics/observability")
def get_observability_snapshot():
    """Unified observability snapshot: metrics, events, traces, security."""
    result: dict = {}
    try:
        from services.observability.metrics import metrics as _metrics_collector
        result["metrics"] = _metrics_collector.get_snapshot()
    except Exception:
        result["metrics"] = {}
    try:
        from services.observability.event_logger import get_recent_events
        result["recent_events"] = get_recent_events(limit=20)
    except Exception:
        result["recent_events"] = []
    try:
        from services.observability.security_audit import get_security_summary
        result["security_summary"] = get_security_summary()
    except Exception:
        result["security_summary"] = {}
    return result
