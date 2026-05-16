"""Tests for Tailscale manager module."""
import json
from unittest.mock import MagicMock, patch

import pytest


class TestIsAvailable:
    @patch("shutil.which", return_value="/usr/bin/tailscale")
    def test_available(self, mock_which):
        from services.tailscale_manager import is_available
        assert is_available() is True

    @patch("shutil.which", return_value=None)
    def test_not_available(self, mock_which):
        from services.tailscale_manager import is_available
        assert is_available() is False


class TestGetStatus:
    @patch("subprocess.run")
    @patch("shutil.which", return_value="/usr/bin/tailscale")
    def test_running(self, mock_which, mock_run):
        from services.tailscale_manager import get_status
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout=json.dumps({
                "BackendState": "Running",
                "Self": {
                    "TailscaleIPs": ["100.64.0.1"],
                    "HostName": "my-machine",
                },
                "CurrentTailnet": {"Name": "my-tailnet"},
            }),
        )
        status = get_status()
        assert status["running"] is True
        assert status["ip"] == "100.64.0.1"
        assert status["hostname"] == "my-machine"

    @patch("subprocess.run")
    @patch("shutil.which", return_value="/usr/bin/tailscale")
    def test_not_running(self, mock_which, mock_run):
        from services.tailscale_manager import get_status
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout=json.dumps({
                "BackendState": "Stopped",
                "Self": {"TailscaleIPs": [], "HostName": ""},
            }),
        )
        status = get_status()
        assert status["running"] is False

    @patch("shutil.which", return_value=None)
    def test_not_installed(self, mock_which):
        from services.tailscale_manager import get_status
        status = get_status()
        assert status["running"] is False
        assert "error" in status

    @patch("subprocess.run", side_effect=Exception("timeout"))
    @patch("shutil.which", return_value="/usr/bin/tailscale")
    def test_command_fails(self, mock_which, mock_run):
        from services.tailscale_manager import get_status
        status = get_status()
        assert status["running"] is False
        assert "error" in status


class TestStartTailscale:
    @patch("subprocess.run")
    @patch("shutil.which", return_value="/usr/bin/tailscale")
    def test_start_success(self, mock_which, mock_run):
        from services.tailscale_manager import start_tailscale
        mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
        result = start_tailscale({})
        assert result["ok"] is True

    @patch("shutil.which", return_value=None)
    def test_start_not_installed(self, mock_which):
        from services.tailscale_manager import start_tailscale
        result = start_tailscale({})
        assert result["ok"] is False

    @patch("subprocess.run")
    @patch("shutil.which", return_value="/usr/bin/tailscale")
    def test_start_with_auth_key(self, mock_which, mock_run):
        from services.tailscale_manager import start_tailscale
        mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
        cfg = {"tailscale_auth_key": "tskey-auth-abc123"}
        result = start_tailscale(cfg)
        assert result["ok"] is True
        # Verify auth key was passed
        call_args = mock_run.call_args
        cmd = call_args[0][0] if call_args[0] else call_args[1].get("args", [])
        assert any("tskey-auth-abc123" in str(a) for a in cmd)


class TestStopTailscale:
    @patch("subprocess.run")
    @patch("shutil.which", return_value="/usr/bin/tailscale")
    def test_stop_success(self, mock_which, mock_run):
        from services.tailscale_manager import stop_tailscale
        mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
        result = stop_tailscale()
        assert result["ok"] is True

    @patch("shutil.which", return_value=None)
    def test_stop_not_installed(self, mock_which):
        from services.tailscale_manager import stop_tailscale
        result = stop_tailscale()
        assert result["ok"] is False


class TestGetTailscaleIP:
    @patch("subprocess.run")
    @patch("shutil.which", return_value="/usr/bin/tailscale")
    def test_returns_ip(self, mock_which, mock_run):
        from services.tailscale_manager import get_tailscale_ip
        mock_run.return_value = MagicMock(returncode=0, stdout="100.64.0.1\n")
        ip = get_tailscale_ip()
        assert ip == "100.64.0.1"

    @patch("shutil.which", return_value=None)
    def test_not_installed(self, mock_which):
        from services.tailscale_manager import get_tailscale_ip
        ip = get_tailscale_ip()
        assert ip is None

    @patch("subprocess.run", side_effect=Exception("fail"))
    @patch("shutil.which", return_value="/usr/bin/tailscale")
    def test_command_error(self, mock_which, mock_run):
        from services.tailscale_manager import get_tailscale_ip
        ip = get_tailscale_ip()
        assert ip is None


class TestGetConnectionUrl:
    @patch("subprocess.run")
    @patch("shutil.which", return_value="/usr/bin/tailscale")
    def test_returns_url(self, mock_which, mock_run):
        from services.tailscale_manager import get_connection_url
        mock_run.return_value = MagicMock(returncode=0, stdout="100.64.0.1\n")
        url = get_connection_url(port=8000)
        assert url == "http://100.64.0.1:8000"

    @patch("shutil.which", return_value=None)
    def test_not_available(self, mock_which):
        from services.tailscale_manager import get_connection_url
        url = get_connection_url()
        assert url is None


class TestFunnel:
    @patch("subprocess.run")
    @patch("shutil.which", return_value="/usr/bin/tailscale")
    def test_funnel_start(self, mock_which, mock_run):
        from services.tailscale_manager import funnel_start
        mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
        result = funnel_start(port=8000)
        assert result["ok"] is True

    @patch("subprocess.run")
    @patch("shutil.which", return_value="/usr/bin/tailscale")
    def test_funnel_stop(self, mock_which, mock_run):
        from services.tailscale_manager import funnel_stop
        mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
        result = funnel_stop(port=8000)
        assert result["ok"] is True

    @patch("shutil.which", return_value=None)
    def test_funnel_not_installed(self, mock_which):
        from services.tailscale_manager import funnel_start
        result = funnel_start()
        assert result["ok"] is False


class TestConfigKeys:
    def test_tailscale_config_exists(self):
        import runtime_safety
        cfg = runtime_safety.load_config()
        assert "tailscale_enabled" in cfg
        assert cfg["tailscale_enabled"] is False
        assert "tailscale_auth_key" in cfg

    def test_tunnel_auth_config_exists(self):
        import runtime_safety
        cfg = runtime_safety.load_config()
        assert "tunnel_token_hash" in cfg
        assert "tunnel_token_created_at" in cfg
        assert "tunnel_token_ttl_hours" in cfg
        assert "tunnel_ip_allowlist" in cfg
        assert "tunnel_audit_enabled" in cfg
        assert "tunnel_audit_retention_days" in cfg
