"""Integration tests: remote access → auth → tunnel → audit logging."""
import pytest
from unittest.mock import patch, MagicMock


class TestTunnelAuthIntegration:
    """Verify the full auth flow: generate → hash → validate → rotate."""

    def test_full_token_lifecycle(self):
        """Generate token → hash → validate → rotate → old token rejected."""
        from services.tunnel_auth import generate_token, hash_token, validate_token, rotate_token

        # 1. Generate and hash
        token = generate_token()
        h = hash_token(token)

        # 2. Validate succeeds
        cfg = {"tunnel_token_hash": h}
        ok, _ = validate_token(token, cfg)
        assert ok is True

        # 3. Rotate
        new_token, new_hash = rotate_token(cfg)
        assert new_token != token
        assert new_hash != h

        # 4. New token works, old still works via fallback if remote_api_key set
        cfg2 = {"tunnel_token_hash": new_hash}
        ok_new, _ = validate_token(new_token, cfg2)
        assert ok_new is True
        ok_old, _ = validate_token(token, cfg2)
        assert ok_old is False  # Old token rejected with new hash

    def test_auth_plus_ip_plus_expiry(self):
        """Combined check: valid token + allowed IP + not expired."""
        from services.tunnel_auth import generate_token, hash_token, check_remote_access
        import datetime

        token = generate_token()
        cfg = {
            "tunnel_token_hash": hash_token(token),
            "tunnel_ip_allowlist": ["10.0.0.1", "10.0.0.2"],
            "tunnel_token_ttl_hours": 24,
            "tunnel_token_created_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        }

        # Valid token + allowed IP
        ok, _ = check_remote_access(token, "10.0.0.1", cfg)
        assert ok is True

        # Valid token + disallowed IP
        ok, reason = check_remote_access(token, "192.168.1.1", cfg)
        assert ok is False

        # Wrong token + allowed IP
        ok, reason = check_remote_access("wrong", "10.0.0.1", cfg)
        assert ok is False


class TestTunnelAuditIntegration:
    """Verify audit logging captures auth decisions."""

    @pytest.fixture(autouse=True)
    def isolate_audit_db(self, tmp_path):
        import services.tunnel_audit as ta
        original_db = ta._DB_PATH
        ta._DB_PATH = tmp_path / "test_audit.db"
        ta._table_ready = False
        yield
        ta._DB_PATH = original_db
        ta._table_ready = False

    def test_log_then_query(self):
        from services.tunnel_audit import log_access, query_log, get_summary

        # Simulate mixed access
        log_access("10.0.0.1", "/agent", "POST", "abc12345", "allow")
        log_access("192.168.1.1", "/admin", "GET", None, "deny", detail="bad token")
        log_access("10.0.0.1", "/health", "GET", "abc12345", "allow")

        # Query all
        entries = query_log(days=1)
        assert len(entries) == 3

        # Query denied only
        denied = query_log(days=1, result_filter="deny")
        assert len(denied) == 1
        assert denied[0]["client_ip"] == "192.168.1.1"

        # Summary
        summary = get_summary(days=1)
        assert summary["total_requests"] == 3
        assert summary["allowed"] == 2
        assert summary["denied"] == 1
        assert summary["unique_ips"] == 2


class TestTunnelManagerIntegration:
    """Verify tunnel manager status/start/stop interface."""

    def test_status_when_not_running(self):
        from services.tunnel_manager import tunnel_status
        status = tunnel_status()
        assert "running" in status
        assert isinstance(status["running"], bool)

    def test_start_without_cloudflared(self):
        """Start should fail gracefully when cloudflared not found."""
        from services.tunnel_manager import start_quick_tunnel
        with patch("shutil.which", return_value=None):
            result = start_quick_tunnel()
            assert result["ok"] is False


class TestTailscaleIntegration:
    def test_availability_check(self):
        from services.tailscale_manager import is_available
        # Just verify it doesn't crash
        result = is_available()
        assert isinstance(result, bool)

    def test_status_when_not_installed(self):
        from services.tailscale_manager import get_status
        with patch("shutil.which", return_value=None):
            status = get_status()
            assert status["running"] is False
