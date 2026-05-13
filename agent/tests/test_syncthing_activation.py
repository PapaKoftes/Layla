"""Tests for Syncthing sync module."""
import pytest
from unittest.mock import patch, MagicMock


class TestIsRunning:
    def test_returns_bool(self):
        from services.syncthing_sync import is_running
        result = is_running()
        assert isinstance(result, bool)

    def test_not_running_without_server(self):
        """Without a Syncthing server, is_running should return False."""
        from services.syncthing_sync import is_running
        # No Syncthing running in test env
        assert is_running() is False


class TestGetStatus:
    def test_returns_dict(self):
        from services.syncthing_sync import get_status
        status = get_status()
        assert isinstance(status, dict)

    def test_has_running_key(self):
        from services.syncthing_sync import get_status
        status = get_status()
        assert "running" in status

    def test_not_running_by_default(self):
        """Without Syncthing configured, should show not running."""
        from services.syncthing_sync import get_status
        status = get_status()
        assert status["running"] is False

    def test_has_enabled_key(self):
        from services.syncthing_sync import get_status
        status = get_status()
        assert "enabled" in status


class TestGetDeviceId:
    def test_returns_none_when_not_running(self):
        """Without Syncthing, device ID should be None."""
        from services.syncthing_sync import get_device_id
        result = get_device_id()
        assert result is None


class TestTriggerRescan:
    def test_returns_dict(self):
        from services.syncthing_sync import trigger_rescan
        result = trigger_rescan()
        assert isinstance(result, dict)

    def test_fails_without_server(self):
        from services.syncthing_sync import trigger_rescan
        result = trigger_rescan()
        assert result.get("ok") is False


class TestAddDevice:
    def test_fails_without_server(self):
        from services.syncthing_sync import add_device
        result = add_device("FAKE-DEVICE-ID-1234")
        assert isinstance(result, dict)
        assert result.get("ok") is False

    def test_empty_device_id(self):
        from services.syncthing_sync import add_device
        result = add_device("")
        assert isinstance(result, dict)
        assert result.get("ok") is False
