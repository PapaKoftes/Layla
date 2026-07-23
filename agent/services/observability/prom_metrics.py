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


def record_context_pressure(pressure: float) -> None:
    """Record current context window pressure ratio (0.0-1.0)."""
    CONTEXT_PRESSURE.set(max(0.0, min(1.0, float(pressure))))


# ---------------------------------------------------------------------------
# Output functions
# ---------------------------------------------------------------------------

def metric_values(metric: Any) -> dict[tuple, Any]:
    """Values of one metric as {label_tuple: number-or-observations}, in EITHER backend.

    The fallback classes expose `.get_all()`; real prometheus_client metrics do not — they expose
    `.collect()`. Callers (including the /summary builder and the tests) must never branch on which
    backend is installed, or the two environments drift and CI goes red on a shape the local venv
    never exercises. This is that single seam.
    """
    if hasattr(metric, "get_all"):
        return metric.get_all()  # fallback: {label_tuple: float | [observations]}
    out: dict[tuple, Any] = {}
    try:
        for fam in metric.collect():
            for s in fam.samples:
                # Skip prometheus internals: creation timestamps and histogram bucket rows.
                if s.name.endswith("_created") or s.name.endswith("_bucket"):
                    continue
                key = tuple(str(v) for v in s.labels.values())
                if s.name.endswith("_count"):
                    out.setdefault(key, {})["count"] = s.value
                elif s.name.endswith("_sum"):
                    out.setdefault(key, {})["sum"] = s.value
                else:
                    # counter `_total` or gauge (bare name): the primary scalar value.
                    if not isinstance(out.get(key), dict):
                        out[key] = s.value
    except Exception:
        pass
    return out


def _summary_scalar(metric: Any) -> dict[str, Any]:
    raw = metric_values(metric)
    return {",".join(k): v for k, v in raw.items()} if raw else {}


def _summary_histogram(metric: Any) -> dict[str, Any]:
    raw = metric_values(metric)
    out: dict[str, Any] = {}
    for k, v in raw.items():
        key = ",".join(k)
        if isinstance(v, dict):  # real prometheus: {count, sum} already extracted
            out[key] = {"count": v.get("count", 0), "sum": v.get("sum", 0.0)}
        else:  # fallback: v is a list of observations
            out[key] = {"count": len(v), "sum": sum(v)}
    return out


def _build_summary() -> dict[str, Any]:
    """One summary shape, whether or not prometheus_client is installed.

    Was two functions returning DIFFERENT shapes: the fallback keyed by tool_calls/llm_requests/…,
    the prometheus path dumping raw REGISTRY sample names (python_gc_objects_collected_total, …). So
    /metrics/summary silently returned garbage in production the moment prometheus was installed, and
    6 tests passed locally (no prometheus) while failing in CI (prometheus present). One builder, one
    contract, both environments.
    """
    summary: dict[str, Any] = {}
    for name, metric in [
        ("tool_calls", TOOL_CALLS), ("memory_ops", MEMORY_OPS),
        ("llm_requests", LLM_REQUESTS), ("scheduler_runs", SCHEDULER_RUNS),
    ]:
        summary[name] = _summary_scalar(metric)
    for name, metric in [
        ("tool_duration", TOOL_DURATION), ("llm_latency", LLM_LATENCY),
        ("embedding_latency", EMBEDDING_LATENCY),
    ]:
        summary[name] = _summary_histogram(metric)
    for name, metric in [
        ("context_pressure", CONTEXT_PRESSURE), ("active_missions", ACTIVE_MISSIONS),
        ("memory_size", MEMORY_SIZE),
    ]:
        summary[name] = _summary_scalar(metric)
    return summary


def generate_metrics_text() -> str | dict:
    """Prometheus text format for the /metrics scrape endpoint when available, else the JSON summary."""
    if PROMETHEUS_AVAILABLE:
        return _generate_latest().decode("utf-8")
    return _build_summary()


def get_metrics_summary() -> dict[str, Any]:
    """A stable JSON summary of all app metrics — identical shape in both backends (see _build_summary)."""
    return _build_summary()


# _build_fallback_summary / _build_prometheus_summary were merged into _build_summary above — they
# returned different shapes for the same endpoint, which is exactly how CI (prometheus present) and
# local (absent) disagreed for 12 days.
