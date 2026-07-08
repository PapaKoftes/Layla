# -*- coding: utf-8 -*-
"""
Tests for Phase 3 observability stack:
  - Metrics service (fallback mode — no prometheus_client required)
  - Crash handler
  - Structured logging wrapper
"""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

AGENT_DIR = Path(__file__).resolve().parent.parent
if str(AGENT_DIR) not in sys.path:
    sys.path.insert(0, str(AGENT_DIR))


# ---------------------------------------------------------------------------
# Tests: Metrics service (fallback mode)
# ---------------------------------------------------------------------------


class TestMetricsFallback:
    """Tests for the lightweight fallback metrics when prometheus_client is absent."""

    def test_record_tool_call(self):
        from services.observability.prom_metrics import TOOL_CALLS, TOOL_DURATION, record_tool_call
        record_tool_call("read_file", True, 0.5)
        counters = TOOL_CALLS.get_all()
        # Should have at least one entry
        assert any(v > 0 for v in counters.values())

    def test_record_llm_request(self):
        from services.observability.prom_metrics import LLM_REQUESTS, record_llm_request
        record_llm_request("test-model.gguf", "morrigan", 1.2)
        counters = LLM_REQUESTS.get_all()
        assert any(v > 0 for v in counters.values())

    def test_record_memory_op(self):
        from services.observability.prom_metrics import MEMORY_OPS, record_memory_op
        record_memory_op("episodic", "save_learning")
        counters = MEMORY_OPS.get_all()
        assert any(v > 0 for v in counters.values())

    def test_record_scheduler_run(self):
        from services.observability.prom_metrics import SCHEDULER_RUNS, record_scheduler_run
        record_scheduler_run("mission_worker", "ok")
        counters = SCHEDULER_RUNS.get_all()
        assert any(v > 0 for v in counters.values())

    def test_get_metrics_summary_returns_dict(self):
        from services.observability.prom_metrics import get_metrics_summary
        summary = get_metrics_summary()
        assert isinstance(summary, dict)
        assert "tool_calls" in summary
        assert "llm_requests" in summary
        assert "memory_ops" in summary

    def test_generate_metrics_text_fallback(self):
        from services.observability.prom_metrics import PROMETHEUS_AVAILABLE, generate_metrics_text
        result = generate_metrics_text()
        if not PROMETHEUS_AVAILABLE:
            assert isinstance(result, dict)
        # Either way, it shouldn't raise

    def test_fallback_counter_inc(self):
        from services.observability.prom_metrics import _FallbackCounter
        c = _FallbackCounter("test_counter", "test", ["label1"])
        c.labels("a").inc()
        c.labels("a").inc()
        c.labels("b").inc()
        all_vals = c.get_all()
        assert all_vals[("a",)] == 2
        assert all_vals[("b",)] == 1

    def test_fallback_histogram_observe(self):
        from services.observability.prom_metrics import _FallbackHistogram
        h = _FallbackHistogram("test_hist", "test", ["label1"])
        h.labels("a").observe(0.5)
        h.labels("a").observe(1.5)
        all_vals = h.get_all()
        assert len(all_vals[("a",)]) == 2
        assert sum(all_vals[("a",)]) == 2.0

    def test_fallback_gauge_set_and_inc_dec(self):
        from services.observability.prom_metrics import _FallbackGauge
        g = _FallbackGauge("test_gauge", "test")
        g.set(10.0)
        assert g.get_all()[()] == 10.0
        g.inc(5.0)
        assert g.get_all()[()] == 15.0
        g.dec(3.0)
        assert g.get_all()[()] == 12.0


# ---------------------------------------------------------------------------
# Tests: Crash handler
# ---------------------------------------------------------------------------


class TestCrashHandler:
    """Tests for the crash dump handler."""

    def test_get_recent_crashes_empty(self):
        from services.infrastructure.crash_handler import get_recent_crashes
        # Should return a list (possibly empty)
        result = get_recent_crashes()
        assert isinstance(result, list)

    def test_crash_dump_writes_json(self, tmp_path):
        """Simulate a crash and verify dump file is valid JSON."""
        import services.infrastructure.crash_handler as ch
        original_dir = ch.CRASH_DIR
        ch.CRASH_DIR = tmp_path / "crashes"

        try:
            ch.install_crash_handler()
            # Simulate a crash by calling excepthook directly
            try:
                raise ValueError("test crash")
            except ValueError:
                import traceback
                exc_type, exc_value, exc_tb = sys.exc_info()
                sys.excepthook(exc_type, exc_value, exc_tb)

            # Check that a crash file was written
            files = list((tmp_path / "crashes").glob("crash_*.json"))
            assert len(files) >= 1
            dump = json.loads(files[0].read_text(encoding="utf-8"))
            assert dump["type"] == "ValueError"
            assert "test crash" in dump["exception"]
        finally:
            ch.CRASH_DIR = original_dir

    def test_clear_crashes(self, tmp_path):
        import services.infrastructure.crash_handler as ch
        from services.infrastructure.crash_handler import clear_crashes
        original_dir = ch.CRASH_DIR
        ch.CRASH_DIR = tmp_path / "crashes"

        try:
            (tmp_path / "crashes").mkdir(parents=True, exist_ok=True)
            (tmp_path / "crashes" / "crash_1.json").write_text("{}")
            (tmp_path / "crashes" / "crash_2.json").write_text("{}")
            count = clear_crashes()
            assert count == 2
        finally:
            ch.CRASH_DIR = original_dir


# ---------------------------------------------------------------------------
# Tests: Structured logging wrapper
# ---------------------------------------------------------------------------


class TestMetricsRouter:
    """Test that the metrics router can be imported and has expected endpoints."""

    def test_router_importable(self):
        from routers.metrics import router
        assert hasattr(router, "routes")

    def test_router_has_metrics_endpoint(self):
        from routers.metrics import router
        paths = [r.path for r in router.routes if hasattr(r, "path")]
        assert "/metrics" in paths
        assert "/metrics/summary" in paths
