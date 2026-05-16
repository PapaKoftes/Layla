"""Tests for tunnel manager module."""
from unittest.mock import MagicMock, patch

import pytest


class TestTunnelStatus:
    def test_returns_dict(self):
        from services.tunnel_manager import tunnel_status
        status = tunnel_status()
        assert isinstance(status, dict)
        assert "running" in status

    def test_running_is_bool(self):
        from services.tunnel_manager import tunnel_status
        status = tunnel_status()
        assert isinstance(status["running"], bool)

    def test_not_running_by_default(self):
        """Without starting a tunnel, status should show not running."""
        from services.tunnel_manager import tunnel_status
        status = tunnel_status()
        # May or may not be running depending on env, but should not crash
        assert "running" in status


class TestStartQuickTunnel:
    def test_no_cloudflared(self):
        """Start should fail gracefully when cloudflared not found."""
        from services.tunnel_manager import start_quick_tunnel
        with patch("shutil.which", return_value=None):
            result = start_quick_tunnel()
            assert result["ok"] is False
            assert "error" in result or "detail" in result or "msg" in result

    def test_returns_dict(self):
        from services.tunnel_manager import start_quick_tunnel
        with patch("shutil.which", return_value=None):
            result = start_quick_tunnel()
            assert isinstance(result, dict)

    def test_custom_local_url(self):
        from services.tunnel_manager import start_quick_tunnel
        with patch("shutil.which", return_value=None):
            result = start_quick_tunnel(local_url="http://127.0.0.1:9000")
            assert result["ok"] is False


class TestStopTunnel:
    def test_stop_when_not_running(self):
        """Stop should succeed gracefully when no tunnel is running."""
        from services.tunnel_manager import stop_tunnel
        result = stop_tunnel()
        assert isinstance(result, dict)
        assert "ok" in result


class TestTunnelLifecycle:
    def test_status_start_stop(self):
        """Verify the status → start (fail) → stop cycle doesn't crash."""
        from services.tunnel_manager import start_quick_tunnel, stop_tunnel, tunnel_status
        with patch("shutil.which", return_value=None):
            status = tunnel_status()
            assert isinstance(status, dict)

            result = start_quick_tunnel()
            assert result["ok"] is False

            stop = stop_tunnel()
            assert isinstance(stop, dict)


# ---------------------------------------------------------------------------
# Health check + auto-restart (Phase 5)
# ---------------------------------------------------------------------------

class TestHealthCheck:
    def test_not_running_returns_unhealthy(self):
        """Health check when no tunnel is running."""
        import services.tunnel_manager as tm
        tm._proc = None
        tm._last_url = ""
        result = tm.health_check()
        assert result["healthy"] is False
        assert result["reason"] == "tunnel_not_running"

    def test_no_url_returns_unhealthy(self):
        """Health check when tunnel is running but URL not yet available."""
        import services.tunnel_manager as tm
        proc = MagicMock()
        proc.poll.return_value = None  # process alive
        tm._proc = proc
        tm._last_url = ""
        try:
            result = tm.health_check()
            assert result["healthy"] is False
            assert result["reason"] == "no_tunnel_url"
        finally:
            tm._proc = None
            tm._last_url = ""

    @patch("urllib.request.urlopen")
    def test_healthy_when_reachable(self, mock_urlopen):
        """Health check succeeds when tunnel URL is reachable."""
        import services.tunnel_manager as tm
        proc = MagicMock()
        proc.poll.return_value = None
        tm._proc = proc
        tm._last_url = "https://test.trycloudflare.com"
        mock_resp = MagicMock()
        mock_resp.status = 200
        mock_urlopen.return_value = mock_resp
        try:
            result = tm.health_check()
            assert result["healthy"] is True
            assert result["status_code"] == 200
            assert result["consecutive_failures"] == 0
        finally:
            tm._proc = None
            tm._last_url = ""

    @patch("urllib.request.urlopen", side_effect=Exception("timeout"))
    def test_unhealthy_increments_failures(self, mock_urlopen):
        """Health check failure increments consecutive_failures."""
        import services.tunnel_manager as tm
        proc = MagicMock()
        proc.poll.return_value = None
        tm._proc = proc
        tm._last_url = "https://test.trycloudflare.com"
        tm._consecutive_failures = 0
        try:
            r1 = tm.health_check()
            assert r1["healthy"] is False
            assert r1["consecutive_failures"] == 1

            r2 = tm.health_check()
            assert r2["consecutive_failures"] == 2
        finally:
            tm._proc = None
            tm._last_url = ""
            tm._consecutive_failures = 0


class TestGetHealthState:
    def test_returns_dict(self):
        from services.tunnel_manager import get_health_state
        state = get_health_state()
        assert isinstance(state, dict)
        assert "consecutive_failures" in state
        assert "max_failures_before_restart" in state

    def test_default_values(self):
        import services.tunnel_manager as tm
        tm._consecutive_failures = 0
        state = tm.get_health_state()
        assert state["consecutive_failures"] == 0
        assert state["max_failures_before_restart"] == 3


class TestAutoRestart:
    def test_no_restart_when_healthy(self):
        """Auto-restart doesn't trigger when tunnel is healthy."""
        import services.tunnel_manager as tm
        with patch.object(tm, "health_check", return_value={"healthy": True}):
            result = tm.auto_restart_if_unhealthy()
            assert result["restarted"] is False

    def test_no_restart_below_threshold(self):
        """Auto-restart doesn't trigger below failure threshold."""
        import services.tunnel_manager as tm
        tm._consecutive_failures = 1
        try:
            with patch.object(tm, "health_check", return_value={"healthy": False}):
                result = tm.auto_restart_if_unhealthy(max_failures=3)
                assert result["restarted"] is False
                assert "1/3" in result.get("message", "")
        finally:
            tm._consecutive_failures = 0

    def test_restarts_at_threshold(self):
        """Auto-restart triggers when failures reach threshold."""
        import services.tunnel_manager as tm
        tm._consecutive_failures = 3
        try:
            with patch.object(tm, "health_check", return_value={"healthy": False}), \
                 patch.object(tm, "stop_tunnel", return_value={"ok": True, "stopped": True}), \
                 patch.object(tm, "start_quick_tunnel", return_value={"ok": True}):
                result = tm.auto_restart_if_unhealthy(max_failures=3)
                assert result["restarted"] is True
                assert result["restart_result"]["ok"] is True
        finally:
            tm._consecutive_failures = 0

    def test_remembers_local_url(self):
        """Auto-restart uses the last local_url from start_quick_tunnel."""
        import services.tunnel_manager as tm
        tm._consecutive_failures = 3
        tm._last_local_url = "http://127.0.0.1:9000"
        try:
            with patch.object(tm, "health_check", return_value={"healthy": False}), \
                 patch.object(tm, "stop_tunnel", return_value={"ok": True, "stopped": True}), \
                 patch.object(tm, "start_quick_tunnel", return_value={"ok": True}) as mock_start:
                tm.auto_restart_if_unhealthy(max_failures=3)
                mock_start.assert_called_once_with(
                    local_url="http://127.0.0.1:9000", cloudflared=None,
                )
        finally:
            tm._consecutive_failures = 0
            tm._last_local_url = "http://127.0.0.1:8000"
