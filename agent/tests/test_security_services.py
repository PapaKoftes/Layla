"""Tests for security-critical services -- auth, URL validation, skill pack sanitization."""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

AGENT_DIR = Path(__file__).resolve().parent.parent
if str(AGENT_DIR) not in sys.path:
    sys.path.insert(0, str(AGENT_DIR))


class TestAuth:
    def test_valid_tunnel_auth(self):
        """check_auth returns True for valid tunnel token."""
        from services.auth import check_auth

        with patch("services.auth.check_remote_access", return_value=(True, "ok"), create=True):
            # Patch the import inside check_auth
            with patch.dict("sys.modules", {"services.tunnel_auth": MagicMock(
                check_remote_access=MagicMock(return_value=(True, "ok"))
            )}):
                ok, reason = check_auth("valid-token", "1.2.3.4", {"tunnel_token_hash": "xxx"})
                assert ok is True

    def test_invalid_token_denied(self):
        """check_auth returns False for invalid token when tunnel_token_hash is set."""
        from services.auth import check_auth

        with patch.dict("sys.modules", {"services.tunnel_auth": MagicMock(
            check_remote_access=MagicMock(return_value=(False, "bad token"))
        )}):
            ok, reason = check_auth("bad-token", "1.2.3.4", {"tunnel_token_hash": "xxx"})
            assert ok is False
            assert "invalid" in reason.lower() or "bad" in reason.lower()

    def test_legacy_api_key_timing_safe(self):
        """Legacy API key comparison uses hmac.compare_digest."""
        import hmac

        from services.auth import check_auth

        # Make tunnel_auth unavailable so it falls through to legacy
        with patch.dict("sys.modules", {"services.tunnel_auth": None}):
            with patch("hmac.compare_digest", wraps=hmac.compare_digest) as mock_cmp:
                check_auth("test-key", "1.2.3.4", {"remote_api_key": "test-key"})
                mock_cmp.assert_called_once()

    def test_no_auth_configured(self):
        """check_auth returns False with 'no auth configured' when nothing is set."""
        from services.auth import check_auth

        # Make tunnel_auth unavailable
        with patch.dict("sys.modules", {"services.tunnel_auth": None}):
            ok, reason = check_auth("any", "1.2.3.4", {})
            assert ok is False
            assert "no auth" in reason

    def test_empty_token(self):
        """check_auth returns False for empty token."""
        from services.auth import check_auth

        with patch.dict("sys.modules", {"services.tunnel_auth": MagicMock(
            check_remote_access=MagicMock(return_value=(False, "empty"))
        )}):
            ok, _ = check_auth("", "1.2.3.4", {"tunnel_token_hash": "xxx"})
            assert ok is False


class TestBrowserSSRF:
    def test_localhost_blocked(self):
        from services.browser import _is_safe_url

        assert _is_safe_url("http://127.0.0.1/admin") is False
        assert _is_safe_url("http://localhost/") is False
        assert _is_safe_url("http://0.0.0.0/") is False

    def test_private_ranges_blocked(self):
        from services.browser import _is_safe_url

        assert _is_safe_url("http://10.0.0.1/") is False
        assert _is_safe_url("http://192.168.1.1/") is False
        assert _is_safe_url("http://172.16.0.1/") is False
        assert _is_safe_url("http://172.31.255.255/") is False
        assert _is_safe_url("http://169.254.1.1/") is False

    def test_public_urls_allowed(self):
        from services.browser import _is_safe_url

        assert _is_safe_url("https://example.com") is True
        assert _is_safe_url("https://api.github.com/repos") is True

    def test_non_http_blocked(self):
        from services.browser import _is_safe_url

        assert _is_safe_url("ftp://example.com") is False
        assert _is_safe_url("file:///etc/passwd") is False
        assert _is_safe_url("javascript:alert(1)") is False

    def test_empty_and_none(self):
        from services.browser import _is_safe_url

        assert _is_safe_url("") is False
        assert _is_safe_url(None) is False

    def test_172_non_private_allowed(self):
        from services.browser import _is_safe_url

        assert _is_safe_url("http://172.32.0.1/") is True
        assert _is_safe_url("http://172.15.0.1/") is True


class TestSkillPackSecurity:
    """Test security validation in install_from_git (URL scheme, credentials, slug)."""

    def test_url_scheme_validation(self):
        """Only https:// and git:// should be allowed."""
        from services.skill_packs import install_from_git

        # Invalid schemes should be rejected before any git clone
        result_http = install_from_git("http://github.com/user/repo.git")
        assert result_http["ok"] is False
        assert "scheme" in result_http["error"].lower() or "not allowed" in result_http["error"].lower()

        result_ftp = install_from_git("ftp://files.example.com/pack.zip")
        assert result_ftp["ok"] is False
        assert "scheme" in result_ftp["error"].lower() or "not allowed" in result_ftp["error"].lower()

    def test_embedded_credentials_blocked(self):
        """URLs with embedded user:pass@ should be rejected."""
        from services.skill_packs import install_from_git

        result = install_from_git("https://user:pass@github.com/repo.git")
        assert result["ok"] is False
        assert "credential" in result["error"].lower()

    def test_slug_validation(self):
        """Slugs with path traversal or invalid chars should be rejected."""
        from services.skill_packs import install_from_git

        # Path traversal slug
        result = install_from_git("https://github.com/user/repo.git", name="../../etc/passwd")
        assert result["ok"] is False
        assert "slug" in result["error"].lower() or "invalid" in result["error"].lower()

        # Slug with spaces
        result = install_from_git("https://github.com/user/repo.git", name="a b c")
        assert result["ok"] is False

        # Empty slug after strip
        result = install_from_git("https://github.com/user/repo.git", name="   ")
        assert result["ok"] is False

    def test_safe_slug_accepted(self):
        """Valid slugs should pass the regex check (pack itself may fail to clone, but slug is OK)."""
        from services.skill_packs import _SAFE_SLUG_RE

        assert _SAFE_SLUG_RE.match("my-pack_v2") is not None
        assert _SAFE_SLUG_RE.match("simple123") is not None
        assert _SAFE_SLUG_RE.match("Pack-Name_v3") is not None

    def test_safe_slug_regex_rejects_bad_input(self):
        """Unsafe slugs should fail the regex."""
        from services.skill_packs import _SAFE_SLUG_RE

        assert _SAFE_SLUG_RE.match("../../etc/passwd") is None
        assert _SAFE_SLUG_RE.match("a b c") is None
        assert _SAFE_SLUG_RE.match("") is None

    def test_allowed_schemes_constant(self):
        """Verify the allowed schemes are exactly https and git."""
        from services.skill_packs import _ALLOWED_SCHEMES

        assert "https://" in _ALLOWED_SCHEMES
        assert "git://" in _ALLOWED_SCHEMES
        assert "http://" not in _ALLOWED_SCHEMES
        assert "ftp://" not in _ALLOWED_SCHEMES
