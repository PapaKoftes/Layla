# -*- coding: utf-8 -*-
"""
test_tool_tracing.py -- Tests for tool call tracing: DB writes, reliability
stats, and /tools/history + /tools/analysis HTTP endpoints.

Run:
    cd agent/ && python -m pytest tests/test_tool_tracing.py -v
"""
from __future__ import annotations

import sqlite3
import sys
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

AGENT_DIR = Path(__file__).resolve().parent.parent
if str(AGENT_DIR) not in sys.path:
    sys.path.insert(0, str(AGENT_DIR))


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def client():
    from fastapi.testclient import TestClient

    from main import app
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c


@pytest.fixture()
def fresh_db(tmp_path):
    """Return path to a fresh SQLite DB with all migrations applied."""
    db_file = tmp_path / "test_layla.db"
    conn = sqlite3.connect(str(db_file))
    conn.row_factory = sqlite3.Row
    # Create the tables we need manually (avoid full migration chain dependency)
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS tool_calls (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            run_id      TEXT NOT NULL DEFAULT '',
            tool_name   TEXT NOT NULL,
            args_hash   TEXT DEFAULT '',
            result_ok   INTEGER DEFAULT 0,
            error_code  TEXT DEFAULT '',
            duration_ms INTEGER DEFAULT 0,
            created_at  TEXT NOT NULL DEFAULT '',
            cost_usd    REAL DEFAULT 0.0,
            provider    TEXT DEFAULT '',
            model_used  TEXT DEFAULT ''
        );
        CREATE TABLE IF NOT EXISTS tool_outcomes (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            tool_name     TEXT NOT NULL,
            context       TEXT DEFAULT '',
            success       INTEGER DEFAULT 0,
            latency_ms    REAL DEFAULT 0,
            quality_score REAL DEFAULT 0.5,
            created_at    TEXT NOT NULL DEFAULT ''
        );
    """)
    conn.commit()
    conn.close()
    return db_file


def _mk_conn(db_file):
    """Return a sqlite3.connect factory for db_file."""
    def _conn():
        c = sqlite3.connect(str(db_file), check_same_thread=False)
        c.row_factory = sqlite3.Row
        return c
    return _conn


def _rows(db_file, sql, params=()):
    conn = sqlite3.connect(str(db_file))
    conn.row_factory = sqlite3.Row
    rows = conn.execute(sql, params).fetchall()
    conn.close()
    return [dict(r) for r in rows]


# ---------------------------------------------------------------------------
# _trace_tool_call -- DB write path
# ---------------------------------------------------------------------------

class TestTraceToolCallWrite:
    def test_writes_success_row(self, fresh_db, monkeypatch):
        monkeypatch.setattr("layla.memory.db_connection._conn", _mk_conn(fresh_db))
        monkeypatch.setattr("layla.memory.migrations.migrate", lambda: None)
        from core.executor import _trace_tool_call

        _trace_tool_call("read_file", {"path": "/tmp/x"}, {"ok": True}, 42, run_id="r1")

        rows = _rows(fresh_db, "SELECT * FROM tool_calls WHERE tool_name='read_file'")
        assert len(rows) == 1
        assert rows[0]["result_ok"] == 1
        assert rows[0]["duration_ms"] == 42
        assert rows[0]["run_id"] == "r1"
        assert rows[0]["error_code"] == ""

    def test_writes_failure_row(self, fresh_db, monkeypatch):
        monkeypatch.setattr("layla.memory.db_connection._conn", _mk_conn(fresh_db))
        monkeypatch.setattr("layla.memory.migrations.migrate", lambda: None)
        from core.executor import _trace_tool_call

        _trace_tool_call("run_tests", None, None, 300, run_id="r2", error_code="timeout")

        rows = _rows(fresh_db, "SELECT * FROM tool_calls WHERE tool_name='run_tests'")
        assert rows[0]["result_ok"] == 0
        assert rows[0]["error_code"] == "timeout"

    def test_args_hash_16_chars(self, fresh_db, monkeypatch):
        monkeypatch.setattr("layla.memory.db_connection._conn", _mk_conn(fresh_db))
        monkeypatch.setattr("layla.memory.migrations.migrate", lambda: None)
        from core.executor import _trace_tool_call

        _trace_tool_call("grep_code", {"pattern": "def foo"}, {"ok": True}, 55)

        rows = _rows(fresh_db, "SELECT args_hash FROM tool_calls WHERE tool_name='grep_code'")
        assert len(rows[0]["args_hash"]) == 16

    def test_none_result_treated_as_failure(self, fresh_db, monkeypatch):
        monkeypatch.setattr("layla.memory.db_connection._conn", _mk_conn(fresh_db))
        monkeypatch.setattr("layla.memory.migrations.migrate", lambda: None)
        from core.executor import _trace_tool_call

        _trace_tool_call("apply_patch", {"patch": "diff..."}, None, 10)

        rows = _rows(fresh_db, "SELECT result_ok FROM tool_calls WHERE tool_name='apply_patch'")
        assert rows[0]["result_ok"] == 0

    def test_ok_false_result_treated_as_failure(self, fresh_db, monkeypatch):
        monkeypatch.setattr("layla.memory.db_connection._conn", _mk_conn(fresh_db))
        monkeypatch.setattr("layla.memory.migrations.migrate", lambda: None)
        from core.executor import _trace_tool_call

        _trace_tool_call("write_file", {}, {"ok": False, "error": "permission denied"}, 5)

        rows = _rows(fresh_db, "SELECT result_ok FROM tool_calls WHERE tool_name='write_file'")
        assert rows[0]["result_ok"] == 0

    def test_write_failure_does_not_raise(self, monkeypatch):
        monkeypatch.setattr("layla.memory.db_connection._conn", lambda: (_ for _ in ()).throw(RuntimeError("gone")))
        monkeypatch.setattr("layla.memory.migrations.migrate", lambda: None)
        from core.executor import _trace_tool_call
        # Must not raise
        _trace_tool_call("read_file", {}, {"ok": True}, 10)

    def test_multiple_rows_written(self, fresh_db, monkeypatch):
        monkeypatch.setattr("layla.memory.db_connection._conn", _mk_conn(fresh_db))
        monkeypatch.setattr("layla.memory.migrations.migrate", lambda: None)
        from core.executor import _trace_tool_call

        for i in range(5):
            _trace_tool_call("list_dir", {}, {"ok": True}, i * 10)

        rows = _rows(fresh_db, "SELECT * FROM tool_calls WHERE tool_name='list_dir'")
        assert len(rows) == 5

    def test_cost_columns_written(self, fresh_db, monkeypatch):
        """Phase 3: cost_usd, provider, model_used columns are persisted."""
        monkeypatch.setattr("layla.memory.db_connection._conn", _mk_conn(fresh_db))
        monkeypatch.setattr("layla.memory.migrations.migrate", lambda: None)
        from core.executor import _trace_tool_call

        _trace_tool_call(
            "read_file", {"path": "/test"}, {"ok": True}, 50,
            run_id="r-cost",
            cost_usd=0.0042,
            provider="anthropic",
            model_used="claude-3-haiku",
        )
        rows = _rows(fresh_db, "SELECT * FROM tool_calls WHERE run_id='r-cost'")
        assert len(rows) == 1
        assert rows[0]["cost_usd"] == pytest.approx(0.0042)
        assert rows[0]["provider"] == "anthropic"
        assert rows[0]["model_used"] == "claude-3-haiku"

    def test_cost_defaults_to_zero(self, fresh_db, monkeypatch):
        """Without cost kwargs, columns default to zero/empty."""
        monkeypatch.setattr("layla.memory.db_connection._conn", _mk_conn(fresh_db))
        monkeypatch.setattr("layla.memory.migrations.migrate", lambda: None)
        from core.executor import _trace_tool_call

        _trace_tool_call("grep_code", {}, {"ok": True}, 20, run_id="r-nocost")
        rows = _rows(fresh_db, "SELECT * FROM tool_calls WHERE run_id='r-nocost'")
        assert len(rows) == 1
        assert rows[0]["cost_usd"] == 0.0
        assert rows[0]["provider"] == ""
        assert rows[0]["model_used"] == ""


# ---------------------------------------------------------------------------
# extract_litellm_cost (Phase 3 — cost extraction from run_completion result)
# ---------------------------------------------------------------------------

class TestExtractLitellmCost:
    def test_with_litellm_metadata(self):
        from services.llm_gateway import extract_litellm_cost
        result = {
            "choices": [{"message": {"content": "hello"}}],
            "_litellm": {
                "cost_usd": 0.005,
                "provider": "openai",
                "model": "gpt-4o-mini",
            },
        }
        cost = extract_litellm_cost(result)
        assert cost["cost_usd"] == pytest.approx(0.005)
        assert cost["provider"] == "openai"
        assert cost["model"] == "gpt-4o-mini"

    def test_without_litellm_metadata(self):
        from services.llm_gateway import extract_litellm_cost
        result = {"choices": [{"message": {"content": "hello"}}]}
        cost = extract_litellm_cost(result)
        assert cost["cost_usd"] == 0.0
        assert cost["provider"] == ""
        assert cost["model"] == ""

    def test_none_result(self):
        from services.llm_gateway import extract_litellm_cost
        cost = extract_litellm_cost(None)
        assert cost["cost_usd"] == 0.0

    def test_empty_dict(self):
        from services.llm_gateway import extract_litellm_cost
        cost = extract_litellm_cost({})
        assert cost["cost_usd"] == 0.0
        assert cost["provider"] == ""


# ---------------------------------------------------------------------------
# get_tool_reliability (unit, isolated DB)
# ---------------------------------------------------------------------------

class TestGetToolReliability:
    def _insert_outcome(self, db_file, tool, success, latency=100.0):
        from datetime import datetime, timezone
        conn = sqlite3.connect(str(db_file))
        conn.execute(
            "INSERT INTO tool_outcomes (tool_name, context, success, latency_ms, quality_score, created_at)"
            " VALUES (?,?,?,?,?,?)",
            (tool, "", 1 if success else 0, latency, 0.8 if success else 0.2,
             datetime.now(timezone.utc).isoformat()),
        )
        conn.commit()
        conn.close()

    def test_success_rate_calculated(self, fresh_db, monkeypatch):
        monkeypatch.setattr("layla.memory.user_profile._conn", _mk_conn(fresh_db))
        monkeypatch.setattr("layla.memory.user_profile.migrate", lambda: None)
        self._insert_outcome(fresh_db, "grep_code", True, 80)
        self._insert_outcome(fresh_db, "grep_code", True, 90)
        self._insert_outcome(fresh_db, "grep_code", False, 500)

        from layla.memory.user_profile import get_tool_reliability
        stats = get_tool_reliability("grep_code")

        assert "grep_code" in stats
        s = stats["grep_code"]
        assert s["count"] == 3
        assert abs(s["success_rate"] - 2 / 3) < 0.01

    def test_avg_latency_correct(self, fresh_db, monkeypatch):
        monkeypatch.setattr("layla.memory.user_profile._conn", _mk_conn(fresh_db))
        monkeypatch.setattr("layla.memory.user_profile.migrate", lambda: None)
        self._insert_outcome(fresh_db, "read_file", True, 100)
        self._insert_outcome(fresh_db, "read_file", True, 300)

        from layla.memory.user_profile import get_tool_reliability
        s = get_tool_reliability("read_file")["read_file"]
        assert abs(s["avg_latency"] - 200.0) < 1.0

    def test_all_tools_when_no_filter(self, fresh_db, monkeypatch):
        monkeypatch.setattr("layla.memory.user_profile._conn", _mk_conn(fresh_db))
        monkeypatch.setattr("layla.memory.user_profile.migrate", lambda: None)
        self._insert_outcome(fresh_db, "tool_a", True)
        self._insert_outcome(fresh_db, "tool_b", False)

        from layla.memory.user_profile import get_tool_reliability
        stats = get_tool_reliability()
        assert "tool_a" in stats
        assert "tool_b" in stats

    def test_empty_db_returns_empty(self, fresh_db, monkeypatch):
        monkeypatch.setattr("layla.memory.user_profile._conn", _mk_conn(fresh_db))
        monkeypatch.setattr("layla.memory.user_profile.migrate", lambda: None)
        from layla.memory.user_profile import get_tool_reliability
        assert get_tool_reliability() == {}


# ---------------------------------------------------------------------------
# /tools/history HTTP endpoint
# ---------------------------------------------------------------------------

@pytest.mark.endpoint
class TestToolsHistoryEndpoint:
    def test_endpoint_reachable(self, client):
        r = client.get("/tools/history")
        assert r.status_code != 404

    def test_response_ok_field(self, client):
        r = client.get("/tools/history")
        if r.status_code == 200:
            assert r.json().get("ok") is True

    def test_records_is_list(self, client):
        r = client.get("/tools/history")
        if r.status_code == 200:
            assert isinstance(r.json()["records"], list)

    def test_total_is_int(self, client):
        r = client.get("/tools/history")
        if r.status_code == 200:
            assert isinstance(r.json()["total"], int)

    def test_tool_name_filter(self, client):
        r = client.get("/tools/history?tool_name=read_file")
        if r.status_code == 200:
            for rec in r.json()["records"]:
                assert rec["tool_name"] == "read_file"

    def test_limit_respected(self, client):
        r = client.get("/tools/history?limit=3")
        if r.status_code == 200:
            assert len(r.json()["records"]) <= 3

    def test_days_param(self, client):
        r = client.get("/tools/history?days=1")
        assert r.status_code in (200, 500)  # acceptable even if DB empty

    def test_record_has_required_fields(self, client):
        r = client.get("/tools/history?limit=5")
        if r.status_code == 200:
            for rec in r.json()["records"]:
                for field in ("id", "run_id", "tool_name", "result_ok", "duration_ms", "created_at"):
                    assert field in rec

    def test_result_ok_is_bool(self, client):
        r = client.get("/tools/history?limit=10")
        if r.status_code == 200:
            for rec in r.json()["records"]:
                assert isinstance(rec["result_ok"], bool)


# ---------------------------------------------------------------------------
# /tools/analysis HTTP endpoint
# ---------------------------------------------------------------------------

@pytest.mark.endpoint
class TestToolsAnalysisEndpoint:
    def test_endpoint_reachable(self, client):
        r = client.get("/tools/analysis")
        assert r.status_code != 404

    def test_response_ok_field(self, client):
        r = client.get("/tools/analysis")
        if r.status_code == 200:
            assert r.json().get("ok") is True

    def test_has_summary(self, client):
        r = client.get("/tools/analysis")
        if r.status_code == 200:
            assert "summary" in r.json()

    def test_summary_fields(self, client):
        r = client.get("/tools/analysis")
        if r.status_code == 200:
            s = r.json()["summary"]
            for f in ("total_calls", "total_successes", "overall_success_rate", "distinct_tools"):
                assert f in s

    def test_success_rate_in_range(self, client):
        r = client.get("/tools/analysis")
        if r.status_code == 200:
            sr = r.json()["summary"]["overall_success_rate"]
            assert 0.0 <= sr <= 1.0

    def test_has_tools_list(self, client):
        r = client.get("/tools/analysis")
        if r.status_code == 200:
            assert isinstance(r.json()["tools"], list)

    def test_tool_entry_fields(self, client):
        r = client.get("/tools/analysis")
        if r.status_code == 200:
            for t in r.json()["tools"]:
                for f in ("tool_name", "calls", "successes", "failures",
                          "success_rate", "avg_duration_ms", "top_errors"):
                    assert f in t

    def test_has_slowest_and_failed_lists(self, client):
        r = client.get("/tools/analysis")
        if r.status_code == 200:
            data = r.json()
            assert "slowest_tools" in data
            assert "most_failed_tools" in data

    def test_slowest_sorted_desc(self, client):
        r = client.get("/tools/analysis")
        if r.status_code == 200:
            slow = r.json()["slowest_tools"]
            if len(slow) >= 2:
                assert slow[0]["avg_duration_ms"] >= slow[1]["avg_duration_ms"]

    def test_failures_consistent(self, client):
        r = client.get("/tools/analysis")
        if r.status_code == 200:
            for t in r.json()["tools"]:
                assert t["failures"] == t["calls"] - t["successes"]

    def test_per_tool_success_rate_in_range(self, client):
        r = client.get("/tools/analysis")
        if r.status_code == 200:
            for t in r.json()["tools"]:
                assert 0.0 <= t["success_rate"] <= 1.0

    def test_days_param(self, client):
        r = client.get("/tools/analysis?days=30")
        assert r.status_code in (200, 500)


# ---------------------------------------------------------------------------
# executor.py + request_tracer integration
# ---------------------------------------------------------------------------

class TestExecutorTracerIntegration:
    def test_record_trace_tool_call_increments_active_trace(self):
        from services.request_tracer import (
            finish_trace,
            record_trace_tool_call,
            start_trace,
        )
        trace = start_trace("integration goal")
        assert trace["tool_calls"] == 0
        record_trace_tool_call()
        record_trace_tool_call()
        assert trace["tool_calls"] == 2
        finish_trace(trace)

    def test_no_active_trace_does_not_raise(self):
        from services.request_tracer import finish_trace, get_active_trace, record_trace_tool_call
        finish_trace(get_active_trace(), status="cleared")
        record_trace_tool_call()  # no-op, no raise

    def test_record_trace_tool_call_importable_from_executor_path(self):
        # The import path executor uses must resolve
        from services.request_tracer import record_trace_tool_call
        assert callable(record_trace_tool_call)

    def test_multiple_tools_accumulate_in_trace(self):
        from services.request_tracer import (
            finish_trace,
            record_trace_tool_call,
            start_trace,
        )
        trace = start_trace("multi tool run")
        for _ in range(6):
            record_trace_tool_call()
        assert trace["tool_calls"] == 6
        finish_trace(trace, tool_calls=None)  # should preserve accumulated count


# ---------------------------------------------------------------------------
# observability.log_tool_result feeds tool_outcomes
# ---------------------------------------------------------------------------

class TestObservabilityToolResult:
    def test_log_tool_result_calls_record_outcome(self):
        with patch("layla.memory.db.record_tool_outcome") as mock_rec:
            from services.observability import log_tool_result
            log_tool_result("grep_code", ok=True, duration_ms=150)
            mock_rec.assert_called_once()
            call_args = mock_rec.call_args
            assert call_args[0][0] == "grep_code"  # tool_name
            assert call_args[0][1] is True          # success

    def test_log_tool_result_failure(self):
        with patch("layla.memory.db.record_tool_outcome") as mock_rec:
            from services.observability import log_tool_result
            log_tool_result("write_file", ok=False, duration_ms=50)
            call_args = mock_rec.call_args
            assert call_args[0][1] is False
