"""
Lightweight in-process metrics collection.

Provides counters, gauges, and timing histograms backed by stdlib only.
All public methods are thread-safe.
"""
from __future__ import annotations

import statistics
import time
from collections import deque
from threading import Lock
from typing import Any, Dict, Optional

_ROLLING_WINDOW = 100  # keep last N timing samples per metric


class MetricsCollector:
    """Singleton-style metrics store.

    Instantiate once at module level (see ``metrics`` below) and import
    wherever you need to record or query metrics.
    """

    def __init__(self) -> None:
        self._lock = Lock()
        self._timings: Dict[str, deque] = {}
        self._counters: Dict[str, float] = {}
        self._gauges: Dict[str, float] = {}

    # -- timings ------------------------------------------------------------

    def record_timing(self, name: str, duration_ms: float) -> None:
        """Append *duration_ms* to the rolling window for *name*.

        Only the last ``_ROLLING_WINDOW`` samples are kept.
        """
        with self._lock:
            if name not in self._timings:
                self._timings[name] = deque(maxlen=_ROLLING_WINDOW)
            self._timings[name].append(duration_ms)

    def get_timing_stats(self, name: str) -> Optional[Dict[str, float]]:
        """Return descriptive statistics for the timing metric *name*.

        Returns ``None`` if no samples have been recorded yet.

        Keys: ``min``, ``max``, ``avg``, ``p50``, ``p95``, ``count``.
        """
        with self._lock:
            samples = list(self._timings.get(name, []))
        if not samples:
            return None
        sorted_samples = sorted(samples)
        count = len(sorted_samples)
        return {
            "min": sorted_samples[0],
            "max": sorted_samples[-1],
            "avg": round(statistics.mean(sorted_samples), 2),
            "p50": round(_percentile(sorted_samples, 50), 2),
            "p95": round(_percentile(sorted_samples, 95), 2),
            "count": count,
        }

    # -- counters -----------------------------------------------------------

    def increment_counter(self, name: str, amount: float = 1) -> None:
        """Atomically increment counter *name* by *amount*."""
        with self._lock:
            self._counters[name] = self._counters.get(name, 0) + amount

    # -- gauges -------------------------------------------------------------

    def record_gauge(self, name: str, value: float) -> None:
        """Set the current gauge value for *name*."""
        with self._lock:
            self._gauges[name] = value

    # -- snapshot -----------------------------------------------------------

    def get_snapshot(self) -> Dict[str, Any]:
        """Return a point-in-time copy of every metric.

        Structure::

            {
                "counters": {"name": value, ...},
                "gauges":   {"name": value, ...},
                "timings":  {"name": {"min": ..., "max": ..., ...}, ...},
            }
        """
        with self._lock:
            counters = dict(self._counters)
            gauges = dict(self._gauges)
            timing_names = list(self._timings.keys())
        timings = {}
        for name in timing_names:
            stats = self.get_timing_stats(name)
            if stats is not None:
                timings[name] = stats
        return {
            "counters": counters,
            "gauges": gauges,
            "timings": timings,
        }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _percentile(sorted_data: list, pct: float) -> float:
    """Compute the *pct*-th percentile from already-sorted data (nearest-rank)."""
    if not sorted_data:
        return 0.0
    k = (pct / 100) * (len(sorted_data) - 1)
    f = int(k)
    c = f + 1
    if c >= len(sorted_data):
        return float(sorted_data[f])
    d = k - f
    return sorted_data[f] + d * (sorted_data[c] - sorted_data[f])


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------

metrics = MetricsCollector()
