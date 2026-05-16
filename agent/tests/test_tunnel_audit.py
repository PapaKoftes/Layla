"""Tests for tunnel audit logging module."""
import os
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest


@pytest.fixture(autouse=True)
def isolate_db(tmp_path):
    """Redirect audit DB to a temp directory for each test."""
    import services.tunnel_audit as ta
    original_db = ta._DB_PATH
    ta._DB_PATH = tmp_path / "test_audit.db"
    ta._table_ready = False  # Reset so table gets created fresh
    yield
    ta._DB_PATH = original_db
    ta._table_ready = False


class TestLogAccess:
    def test_log_allow(self):
        from services.tunnel_audit import log_access, query_log
        log_access("1.2.3.4", "/agent", "POST", "abc12345", "allow")
        entries = query_log(days=1)
        assert len(entries) == 1
        assert entries[0]["client_ip"] == "1.2.3.4"
        assert entries[0]["result"] == "allow"

    def test_log_deny(self):
        from services.tunnel_audit import log_access, query_log
        log_access("9.9.9.9", "/admin", "GET", None, "deny", detail="bad token")
        entries = query_log(days=1)
        assert len(entries) == 1
        assert entries[0]["result"] == "deny"
        assert "bad token" in entries[0]["detail"]

    def test_multiple_entries(self):
        from services.tunnel_audit import log_access, query_log
        for i in range(5):
            log_access(f"10.0.0.{i}", "/health", "GET", None, "allow")
        entries = query_log(days=1)
        assert len(entries) == 5

    def test_never_raises(self):
        """Audit logging should never crash the server."""
        from services.tunnel_audit import log_access
        # Even with bizarre inputs, should not raise
        log_access(None, None, None, None, "allow")


class TestQueryLog:
    def test_empty_db(self):
        from services.tunnel_audit import query_log
        entries = query_log(days=1)
        assert entries == []

    def test_limit(self):
        from services.tunnel_audit import log_access, query_log
        for i in range(20):
            log_access("1.2.3.4", "/test", "GET", None, "allow")
        entries = query_log(days=1, limit=5)
        assert len(entries) == 5

    def test_result_filter_allow(self):
        from services.tunnel_audit import log_access, query_log
        log_access("1.1.1.1", "/a", "GET", None, "allow")
        log_access("2.2.2.2", "/b", "GET", None, "deny")
        log_access("3.3.3.3", "/c", "GET", None, "allow")
        entries = query_log(days=1, result_filter="allow")
        assert len(entries) == 2
        assert all(e["result"] == "allow" for e in entries)

    def test_result_filter_deny(self):
        from services.tunnel_audit import log_access, query_log
        log_access("1.1.1.1", "/a", "GET", None, "allow")
        log_access("2.2.2.2", "/b", "GET", None, "deny")
        entries = query_log(days=1, result_filter="deny")
        assert len(entries) == 1
        assert entries[0]["result"] == "deny"

    def test_entries_ordered_newest_first(self):
        from services.tunnel_audit import log_access, query_log
        log_access("1.1.1.1", "/first", "GET", None, "allow")
        log_access("2.2.2.2", "/second", "GET", None, "allow")
        entries = query_log(days=1)
        assert entries[0]["path"] == "/second"
        assert entries[1]["path"] == "/first"


class TestGetSummary:
    def test_empty_summary(self):
        from services.tunnel_audit import get_summary
        s = get_summary(days=1)
        assert s["total_requests"] == 0
        assert s["allowed"] == 0
        assert s["denied"] == 0

    def test_summary_counts(self):
        from services.tunnel_audit import get_summary, log_access
        log_access("1.1.1.1", "/a", "GET", None, "allow")
        log_access("2.2.2.2", "/b", "POST", None, "deny")
        log_access("1.1.1.1", "/a", "GET", None, "allow")
        s = get_summary(days=1)
        assert s["total_requests"] == 3
        assert s["allowed"] == 2
        assert s["denied"] == 1
        assert s["unique_ips"] >= 2

    def test_top_paths(self):
        from services.tunnel_audit import get_summary, log_access
        for _ in range(5):
            log_access("1.1.1.1", "/popular", "GET", None, "allow")
        log_access("1.1.1.1", "/rare", "GET", None, "allow")
        s = get_summary(days=1)
        assert len(s["top_paths"]) >= 1
        # /popular should be the top path
        assert s["top_paths"][0][0] == "/popular"


class TestPurgeOld:
    def test_purge_empty(self):
        from services.tunnel_audit import purge_old
        count = purge_old(days=1)
        assert count == 0

    def test_purge_recent_keeps(self):
        from services.tunnel_audit import log_access, purge_old, query_log
        log_access("1.1.1.1", "/test", "GET", None, "allow")
        count = purge_old(days=1)
        assert count == 0
        assert len(query_log(days=1)) == 1

    def test_never_raises(self):
        from services.tunnel_audit import purge_old
        # Should not raise even with weird inputs
        purge_old(days=0)
        purge_old(days=-1)


class TestTableCreation:
    def test_auto_creates_table(self):
        from services.tunnel_audit import log_access, query_log
        # First call should auto-create the table
        log_access("1.1.1.1", "/test", "GET", None, "allow")
        assert len(query_log(days=1)) == 1

    def test_idempotent_creation(self):
        from services.tunnel_audit import _ensure_table, log_access, query_log
        _ensure_table()
        _ensure_table()  # Should not raise
        log_access("1.1.1.1", "/test", "GET", None, "allow")
        assert len(query_log(days=1)) == 1
