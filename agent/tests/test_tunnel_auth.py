"""Tests for tunnel authentication module."""
import hashlib
import time
from unittest.mock import patch

import pytest


class TestGenerateToken:
    def test_returns_string(self):
        from services.tunnel_auth import generate_token
        token = generate_token()
        assert isinstance(token, str)
        assert len(token) > 20

    def test_unique_each_call(self):
        from services.tunnel_auth import generate_token
        t1 = generate_token()
        t2 = generate_token()
        assert t1 != t2


class TestHashToken:
    def test_returns_hex(self):
        from services.tunnel_auth import hash_token
        h = hash_token("my-secret-token")
        assert isinstance(h, str)
        assert len(h) == 64  # SHA-256 hex

    def test_deterministic(self):
        from services.tunnel_auth import hash_token
        h1 = hash_token("same")
        h2 = hash_token("same")
        assert h1 == h2

    def test_different_inputs_different_hashes(self):
        from services.tunnel_auth import hash_token
        h1 = hash_token("token-a")
        h2 = hash_token("token-b")
        assert h1 != h2

    def test_matches_stdlib(self):
        from services.tunnel_auth import hash_token
        token = "test-token-123"
        expected = hashlib.sha256(token.encode("utf-8")).hexdigest()
        assert hash_token(token) == expected


class TestValidateToken:
    def test_valid_hashed_token(self):
        from services.tunnel_auth import generate_token, hash_token, validate_token
        token = generate_token()
        h = hash_token(token)
        cfg = {"tunnel_token_hash": h}
        ok, reason = validate_token(token, cfg)
        assert ok is True

    def test_invalid_token(self):
        from services.tunnel_auth import hash_token, validate_token
        cfg = {"tunnel_token_hash": hash_token("correct-token")}
        ok, reason = validate_token("wrong-token", cfg)
        assert ok is False
        assert "invalid" in reason.lower() or "mismatch" in reason.lower()

    def test_backward_compat_plaintext(self):
        from services.tunnel_auth import validate_token
        cfg = {"remote_api_key": "my-old-key"}
        ok, reason = validate_token("my-old-key", cfg)
        assert ok is True

    def test_backward_compat_wrong(self):
        from services.tunnel_auth import validate_token
        cfg = {"remote_api_key": "my-old-key"}
        ok, reason = validate_token("wrong-key", cfg)
        assert ok is False

    def test_no_token_configured(self):
        from services.tunnel_auth import validate_token
        ok, reason = validate_token("any-token", cfg={})
        assert ok is False
        assert "configured" in reason.lower() or "no token" in reason.lower()

    def test_empty_token(self):
        from services.tunnel_auth import validate_token
        cfg = {"tunnel_token_hash": "abc123"}
        ok, reason = validate_token("", cfg)
        assert ok is False

    def test_hash_preferred_over_plaintext(self):
        """When both tunnel_token_hash and remote_api_key exist, hash is tried first."""
        from services.tunnel_auth import hash_token, validate_token
        token = "new-token"
        cfg = {
            "tunnel_token_hash": hash_token(token),
            "remote_api_key": "old-plaintext-key",
        }
        ok, _ = validate_token(token, cfg)
        assert ok is True
        # Legacy key still works during migration (intentional fallthrough)
        ok2, _ = validate_token("old-plaintext-key", cfg)
        assert ok2 is True  # backward compat during migration

    def test_wrong_token_denied_with_both(self):
        """A completely wrong token is denied even with both auth methods configured."""
        from services.tunnel_auth import hash_token, validate_token
        cfg = {
            "tunnel_token_hash": hash_token("new-token"),
            "remote_api_key": "old-plaintext-key",
        }
        ok, _ = validate_token("totally-wrong", cfg)
        assert ok is False


class TestRotateToken:
    def test_returns_token_and_hash(self):
        from services.tunnel_auth import hash_token, rotate_token
        cfg = {}
        new_token, new_hash = rotate_token(cfg)
        assert isinstance(new_token, str)
        assert isinstance(new_hash, str)
        assert len(new_token) > 20
        assert hash_token(new_token) == new_hash

    def test_rotation_creates_different_token(self):
        from services.tunnel_auth import rotate_token
        cfg = {}
        t1, _ = rotate_token(cfg)
        t2, _ = rotate_token(cfg)
        assert t1 != t2


class TestIPAllowlist:
    def test_empty_allowlist_allows_all(self):
        from services.tunnel_auth import is_ip_allowed
        cfg = {"tunnel_ip_allowlist": []}
        assert is_ip_allowed("1.2.3.4", cfg) is True

    def test_no_allowlist_allows_all(self):
        from services.tunnel_auth import is_ip_allowed
        assert is_ip_allowed("1.2.3.4", cfg={}) is True

    def test_ip_in_allowlist(self):
        from services.tunnel_auth import is_ip_allowed
        cfg = {"tunnel_ip_allowlist": ["1.2.3.4", "5.6.7.8"]}
        assert is_ip_allowed("1.2.3.4", cfg) is True

    def test_ip_not_in_allowlist(self):
        from services.tunnel_auth import is_ip_allowed
        cfg = {"tunnel_ip_allowlist": ["1.2.3.4", "5.6.7.8"]}
        assert is_ip_allowed("9.9.9.9", cfg) is False

    def test_localhost_always_allowed(self):
        from services.tunnel_auth import is_ip_allowed
        cfg = {"tunnel_ip_allowlist": ["1.2.3.4"]}
        assert is_ip_allowed("127.0.0.1", cfg) is True
        assert is_ip_allowed("::1", cfg) is True


class TestTokenExpiry:
    def test_no_ttl_never_expires(self):
        from services.tunnel_auth import is_token_expired
        cfg = {"tunnel_token_ttl_hours": 0, "tunnel_token_created_at": "2020-01-01T00:00:00"}
        assert is_token_expired(cfg) is False

    def test_no_created_at_not_expired(self):
        from services.tunnel_auth import is_token_expired
        cfg = {"tunnel_token_ttl_hours": 24}
        assert is_token_expired(cfg) is False

    def test_recent_token_not_expired(self):
        import datetime

        from services.tunnel_auth import is_token_expired
        now = datetime.datetime.now(datetime.timezone.utc).isoformat()
        cfg = {"tunnel_token_ttl_hours": 24, "tunnel_token_created_at": now}
        assert is_token_expired(cfg) is False

    def test_old_token_expired(self):
        from services.tunnel_auth import is_token_expired
        cfg = {"tunnel_token_ttl_hours": 1, "tunnel_token_created_at": "2020-01-01T00:00:00"}
        assert is_token_expired(cfg) is True


class TestCheckRemoteAccess:
    def test_full_valid_access(self):
        from services.tunnel_auth import check_remote_access, generate_token, hash_token
        token = generate_token()
        cfg = {"tunnel_token_hash": hash_token(token), "tunnel_ip_allowlist": []}
        ok, reason = check_remote_access(token, "1.2.3.4", cfg)
        assert ok is True

    def test_denied_bad_token(self):
        from services.tunnel_auth import check_remote_access, hash_token
        cfg = {"tunnel_token_hash": hash_token("good-token")}
        ok, reason = check_remote_access("bad-token", "1.2.3.4", cfg)
        assert ok is False

    def test_denied_ip_not_allowed(self):
        from services.tunnel_auth import check_remote_access, generate_token, hash_token
        token = generate_token()
        cfg = {
            "tunnel_token_hash": hash_token(token),
            "tunnel_ip_allowlist": ["10.0.0.1"],
        }
        ok, reason = check_remote_access(token, "9.9.9.9", cfg)
        assert ok is False

    def test_denied_expired_token(self):
        from services.tunnel_auth import check_remote_access, generate_token, hash_token
        token = generate_token()
        cfg = {
            "tunnel_token_hash": hash_token(token),
            "tunnel_token_ttl_hours": 1,
            "tunnel_token_created_at": "2020-01-01T00:00:00",
        }
        ok, reason = check_remote_access(token, "1.2.3.4", cfg)
        assert ok is False
        assert "expired" in reason.lower()
