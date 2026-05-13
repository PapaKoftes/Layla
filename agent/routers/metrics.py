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
