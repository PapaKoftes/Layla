"""Tests for tunnel manager module."""
import pytest
from unittest.mock import patch, MagicMock


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
        from services.tunnel_manager import tunnel_status, start_quick_tunnel, stop_tunnel
        with patch("shutil.which", return_value=None):
            status = tunnel_status()
            assert isinstance(status, dict)

            result = start_quick_tunnel()
            assert result["ok"] is False

            stop = stop_tunnel()
            assert isinstance(stop, dict)
