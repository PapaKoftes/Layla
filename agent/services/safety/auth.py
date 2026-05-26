"""Shared authentication helpers for HTTP and WebSocket endpoints.

Extracted from ``main.py`` remote_auth_middleware so that the same logic
can protect WebSocket upgrade requests.
"""
from __future__ import annotations

import hmac
import logging

logger = logging.getLogger("layla")


def _is_localhost(host: str | None) -> bool:
    """Return True when *host* is any loopback representation."""
    if not host:
        return True  # conservative: no host info → treat as local
    try:
        from constants import LOCALHOST_HOSTS
        return host in LOCALHOST_HOSTS
    except ImportError:
        return host in ("127.0.0.1", "::1", "localhost", "0.0.0.0", "testclient")


def check_auth(token: str, client_host: str, cfg: dict) -> tuple[bool, str]:
    """Validate a bearer token against the remote auth config.

    Returns ``(ok, reason)`` where *reason* explains the denial (or "ok").

    **Note:** Callers are responsible for localhost bypass and
    ``remote_enabled`` checks.  This function only validates the token.
    """
    # Try tunnel_auth (hashed token + IP allowlist + expiry) first
    auth_ok = False
    try:
        from services.tunnel_auth import check_remote_access

        auth_ok, auth_reason = check_remote_access(token, client_host, cfg)
        if not auth_ok:
            logger.debug("tunnel_auth denied: %s", auth_reason)
    except ImportError:
        pass  # tunnel_auth not available, fall through to legacy

    # Legacy fallback: plaintext remote_api_key (deprecated)
    if not auth_ok:
        api_key = cfg.get("remote_api_key")
        if api_key and str(api_key).strip():
            logger.warning(
                "remote_api_key is deprecated — use tunnel_token_hash via /remote/token/rotate"
            )
            if hmac.compare_digest(token, str(api_key).strip()):
                auth_ok = True

    if auth_ok:
        return True, "ok"

    detail = (
        "no auth configured"
        if not cfg.get("tunnel_token_hash") and not cfg.get("remote_api_key")
        else "invalid token"
    )
    return False, detail
