"""
Prometheus-compatible metrics registry with graceful fallback.

Works with or without prometheus_client installed.
When prometheus_client is absent, uses a lightweight internal
counter/histogram/gauge implementation backed by dicts + threading.Lock.
"""
from __future__ import annotations

import json
import threading
import time
from typing import Any

PROMETHEUS_AVAILABLE = False

try:
    from prometheus_client import Counter, Gauge, Histogram
    from prometheus_client import generate_latest as _generate_latest
    PROMETHEUS_AVAILABLE = True
except ImportError:
    pass


# ---------------------------------------------------------------------------
# Lightweight fallback metric types
# ---------------------------------------------------------------------------

class _FallbackCounter:
    """Thread-safe counter that mimics prometheus_client.Counter."""

    def __init__(self, name: str, doc: str, labelnames: list[str] | None = None):
        self.name = name
        self.doc = doc
        self._labelnames = labelnames or []
        self._values: dict[tuple, float] = {}
        self._lock = threading.Lock()

    def labels(self, *args: str, **kwargs: str) -> "_FallbackCounter":
        key = args if args else tuple(kwargs.get(l, "") for l in self._labelnames)
        child = _FallbackCounter(self.name, self.doc)
        child._values = self._values
        child._lock = self._lock
        child._key = key
        return child

    def inc(self, amount: float = 1) -> None:
        key = getattr(self, "_key", ())
        with self._lock:
            self._values[key] = self._values.get(key, 0) + amount

    def get_all(self) -> dict[tuple, float]:
        with self._lock:
            return dict(self._values)


class _FallbackHistogram:
    """Thread-safe histogram that mimics prometheus_client.Histogram."""

    def __init__(self, name: str, doc: str, labelnames: list[str] | None = None):
        self.name = name
        self.doc = doc
        self._labelnames = labelnames or []
        self._values: dict[tuple, list[float]] = {}
        self._lock = threading.Lock()

    def labels(self, *args: str, **kwargs: str) -> "_FallbackHistogram":
        key = args if args else tuple(kwargs.get(l, "") for l in self._labelnames)
        child = _FallbackHistogram(self.name, self.doc)
        child._values = self._values
        child._lock = self._lock
        child._key = key
        return child

    def observe(self, amount: float) -> None:
        key = getattr(self, "_key", ())
        with self._lock:
            self._values.setdefault(key, []).append(amount)

    def get_all(self) -> dict[tuple, list[float]]:
        with self._lock:
            return {k: list(v) for k, v in self._values.items()}


class _FallbackGauge:
    """Thread-safe gauge that mimics prometheus_client.Gauge."""

    def __init__(self, name: str, doc: str, labelnames: list[str] | None = None):
        self.name = name
        self.doc = doc
        self._labelnames = labelnames or []
        self._values: dict[tuple, float] = {}
        self._lock = threading.Lock()

    def labels(self, *args: str, **kwargs: str) -> "_FallbackGauge":
        key = args if args else tuple(kwargs.get(l, "") for l in self._labelnames)
        child = _FallbackGauge(self.name, self.doc)
        child._values = self._values
        child._lock = self._lock
        child._key = key
        return child

    def set(self, value: float) -> None:
        key = getattr(self, "_key", ())
        with self._lock:
            self._values[key] = value

    def inc(self, amount: float = 1) -> None:
        key = getattr(self, "_key", ())
        with self._lock:
            self._values[key] = self._values.get(key, 0) + amount

    def dec(self, amount: float = 1) -> None:
        key = getattr(self, "_key", ())
        with self._lock:
            self._values[key] = self._values.get(key, 0) - amount

    def get_all(self) -> dict[tuple, float]:
        with self._lock:
            return dict(self._values)


# ---------------------------------------------------------------------------
# Metric definitions
# ---------------------------------------------------------------------------

if PROMETHEUS_AVAILABLE:
    TOOL_CALLS = Counter("layla_tool_calls_total", "Total tool calls", ["tool_name", "result"])
    MEMORY_OPS = Counter("layla_memory_ops_total", "Memory operations", ["layer", "op"])
    LLM_REQUESTS = Counter("layla_llm_requests_total", "LLM requests", ["model", "aspect_id"])
    SCHEDULER_RUNS = Counter("layla_scheduler_runs_total", "Scheduler job runs", ["job_name", "status"])
    TOOL_DURATION = Histogram("layla_tool_duration_seconds", "Tool call duration", ["tool_name"])
    LLM_LATENCY = Histogram("layla_llm_latency_seconds", "LLM request latency", ["model"])
    EMBEDDING_LATENCY = Histogram("layla_embedding_latency_seconds", "Embedding latency")
    CONTEXT_PRESSURE = Gauge("layla_context_pressure_ratio", "Context window pressure")
    ACTIVE_MISSIONS = Gauge("layla_active_missions", "Currently running missions")
    MEMORY_SIZE = Gauge("layla_memory_entries", "Total memory entries", ["type"])
else:
    TOOL_CALLS = _FallbackCounter("layla_tool_calls_total", "Total tool calls", ["tool_name", "result"])
    MEMORY_OPS = _FallbackCounter("layla_memory_ops_total", "Memory operations", ["layer", "op"])
    LLM_REQUESTS = _FallbackCounter("layla_llm_requests_total", "LLM requests", ["model", "aspect_id"])
    SCHEDULER_RUNS = _FallbackCounter("layla_scheduler_runs_total", "Scheduler job runs", ["job_name", "status"])
    TOOL_DURATION = _FallbackHistogram("layla_tool_duration_seconds", "Tool call duration", ["tool_name"])
    LLM_LATENCY = _FallbackHistogram("layla_llm_latency_seconds", "LLM request latency", ["model"])
    EMBEDDING_LATENCY = _FallbackHistogram("layla_embedding_latency_seconds", "Embedding latency")
    CONTEXT_PRESSURE = _FallbackGauge("layla_context_pressure_ratio", "Context window pressure")
    ACTIVE_MISSIONS = _FallbackGauge("layla_active_missions", "Currently running missions")
    MEMORY_SIZE = _FallbackGauge("layla_memory_entries", "Total memory entries", ["type"])


# ---------------------------------------------------------------------------
# Helper functions
# ---------------------------------------------------------------------------

def record_tool_call(tool_name: str, result_ok: bool, duration_seconds: float) -> None:
    """Record a tool call metric."""
    result = "ok" if result_ok else "error"
    TOOL_CALLS.labels(tool_name=tool_name, result=result).inc()
    TOOL_DURATION.labels(tool_name=tool_name).observe(duration_seconds)


def record_llm_request(model: str, aspect_id: str, latency_seconds: float) -> None:
    """Record an LLM request metric."""
    LLM_REQUESTS.labels(model=model, aspect_id=aspect_id).inc()
    LLM_LATENCY.labels(model=model).observe(latency_seconds)


def record_memory_op(layer: str, op: str) -> None:
    """Record a memory operation metric."""
    MEMORY_OPS.labels(layer=layer, op=op).inc()


def record_scheduler_run(job_name: str, status: str) -> None:
    """Record a scheduler job run metric."""
    SCHEDULER_RUNS.labels(job_name=job_name, status=status).inc()


# ---------------------------------------------------------------------------
# Output functions
# ---------------------------------------------------------------------------

def generate_metrics_text() -> str | dict:
    """Return prometheus text format if prometheus_client available, otherwise a JSON-serialisable dict."""
    if PROMETHEUS_AVAILABLE:
        return _generate_latest().decode("utf-8")
    return _build_fallback_summary()


def get_metrics_summary() -> dict[str, Any]:
    """Return a dict of all metric values."""
    if PROMETHEUS_AVAILABLE:
        return _build_prometheus_summary()
    return _build_fallback_summary()


def _build_fallback_summary() -> dict[str, Any]:
    summary: dict[str, Any] = {}
    for name, metric in [
        ("tool_calls", TOOL_CALLS), ("memory_ops", MEMORY_OPS),
        ("llm_requests", LLM_REQUESTS), ("scheduler_runs", SCHEDULER_RUNS),
    ]:
        raw = metric.get_all()
        summary[name] = {",".join(k): v for k, v in raw.items()} if raw else {}
    for name, metric in [
        ("tool_duration", TOOL_DURATION), ("llm_latency", LLM_LATENCY),
        ("embedding_latency", EMBEDDING_LATENCY),
    ]:
        raw = metric.get_all()
        summary[name] = {
            ",".join(k): {"count": len(v), "sum": sum(v)} for k, v in raw.items()
        } if raw else {}
    for name, metric in [
        ("context_pressure", CONTEXT_PRESSURE), ("active_missions", ACTIVE_MISSIONS),
        ("memory_size", MEMORY_SIZE),
    ]:
        raw = metric.get_all()
        summary[name] = {",".join(k): v for k, v in raw.items()} if raw else {}
    return summary


def _build_prometheus_summary() -> dict[str, Any]:
    """Extract values from prometheus_client registry into a plain dict."""
    try:
        from prometheus_client import REGISTRY
        summary: dict[str, Any] = {}
        for metric in REGISTRY.collect():
            for sample in metric.samples:
                key = sample.name
                labels = sample.labels
                label_str = ",".join(f"{k}={v}" for k, v in labels.items()) if labels else ""
                full_key = f"{key}{{{label_str}}}" if label_str else key
                summary[full_key] = sample.value
        return summary
    except Exception:
        return {"error": "failed to collect prometheus metrics"}
