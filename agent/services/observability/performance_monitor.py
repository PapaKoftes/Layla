"""
Performance monitor. Tracks runtime metrics: token throughput, retrieval latency,
tool latency, resource usage. Uses these to adjust system behavior.
"""
from __future__ import annotations

import logging
import time
from collections import deque
from dataclasses import dataclass, field
from threading import Lock

logger = logging.getLogger("layla")

_lock = Lock()
_metrics: dict[str, deque] = {}
_MAX_SAMPLES = 500


@dataclass
class MetricSample:
    """A single metric sample."""

    value: float
    timestamp: float = field(default_factory=time.time)
    tags: dict[str, str] = field(default_factory=dict)


def _get_queue(key: str) -> deque:
    with _lock:
        if key not in _metrics:
            _metrics[key] = deque(maxlen=_MAX_SAMPLES)
        return _metrics[key]


def record(metric: str, value: float, tags: dict[str, str] | None = None) -> None:
    """Record a metric sample."""
    q = _get_queue(metric)
    q.append(MetricSample(value=value, tags=tags or {}))


def record_tool_latency(tool_name: str, latency_ms: float) -> None:
    """Record tool execution latency."""
    record("tool_latency_ms", latency_ms, {"tool": tool_name})
    record(f"tool_latency_{tool_name}", latency_ms)


def record_retrieval_latency(latency_ms: float, source: str = "vector") -> None:
    """Record RAG retrieval latency."""
    record("retrieval_latency_ms", latency_ms, {"source": source})


def record_token_throughput(tokens_per_sec: float) -> None:
    """Record LLM token throughput."""
    record("token_throughput", tokens_per_sec)


def record_memory_mb(mb: float) -> None:
    """Record memory usage sample."""
    record("memory_mb", mb)


def get_stats(metric: str, window_sec: float = 300) -> dict:
    """
    Get stats for a metric over the last window_sec.
    Returns {count, mean, p50, p95, min, max}.
    """
    q = _get_queue(metric)
    cutoff = time.time() - window_sec
    samples = [s.value for s in q if s.timestamp >= cutoff]
    if not samples:
        return {"count": 0, "mean": 0, "p50": 0, "p95": 0, "min": 0, "max": 0}
    samples = sorted(samples)
    n = len(samples)
    return {
        "count": n,
        "mean": round(sum(samples) / n, 2),
        "p50": round(samples[int(n * 0.5)] if n else 0, 2),
        "p95": round(samples[int(n * 0.95)] if n > 1 else samples[0], 2),
        "min": round(samples[0], 2),
        "max": round(samples[-1], 2),
    }


def get_tool_latency_stats(tool_name: str | None = None, window_sec: float = 300) -> dict:
    """Get tool latency stats, optionally filtered by tool."""
    q = _get_queue("tool_latency_ms")
    cutoff = time.time() - window_sec
    if tool_name:
        samples = [s.value for s in q if s.timestamp >= cutoff and s.tags.get("tool") == tool_name]
    else:
        samples = [s.value for s in q if s.timestamp >= cutoff]
    if not samples:
        return {"count": 0, "mean_ms": 0, "p95_ms": 0}
    samples = sorted(samples)
    n = len(samples)
    return {
        "count": n,
        "mean_ms": round(sum(samples) / n, 2),
        "p95_ms": round(samples[int(n * 0.95)] if n > 1 else samples[0], 2),
    }


def get_summary() -> dict:
    """Get summary of all tracked metrics for diagnostics."""
    with _lock:
        keys = list(_metrics.keys())
    out = {}
    for k in keys:
        s = get_stats(k)
        if s["count"] > 0:
            out[k] = s
    return out


def clear() -> None:
    """Clear all metrics (e.g. for tests)."""
    with _lock:
        _metrics.clear()
