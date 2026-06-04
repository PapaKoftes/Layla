"""Shared authentication helpers for HTTP and WebSocket endpoints.

Extracted from ``main.py`` remote_auth_middleware so that the same logic
can protect WebSocket upgrade requests.
"""
from __future__ import annotations

import hmac
import logging
import re

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


# Headers a reverse proxy / tunnel (cloudflared, ngrok, nginx) adds when relaying
# a request. A genuine DIRECT connection has none of them.
_FORWARD_HEADERS = ("x-forwarded-for", "forwarded", "cf-connecting-ip", "x-real-ip", "true-client-ip")


def real_client_ip(headers, socket_host: str | None) -> tuple[str | None, bool]:
    """Return ``(client_ip, via_proxy)``.

    ``via_proxy`` is True when the request carries a forwarding header — i.e. it
    arrived through a reverse proxy or tunnel rather than directly. In that case
    the loopback *socket* address must NOT be trusted as "local": cloudflared and
    ngrok forward internet traffic to the app from 127.0.0.1, so without this the
    entire remote-auth stack is bypassed for tunnelled requests. The real client
    IP is parsed from the header for allowlist / rate-limit / audit use.
    """
    get = getattr(headers, "get", None)
    if callable(get):
        for h in _FORWARD_HEADERS:
            v = get(h)
            if v:
                v = str(v).strip()
                if h == "forwarded":
                    m = re.search(r'for="?\[?([^;,"\]]+)', v, re.IGNORECASE)
                    ip = (m.group(1).strip() if m else v)
                else:
                    ip = v.split(",")[0].strip()
                return (ip or socket_host), True
    return socket_host, False


def is_direct_local(headers, socket_host: str | None) -> bool:
    """True only for a DIRECT loopback request (no proxy/tunnel in front).

    Use this — not a bare host check — for any "trust the local caller" decision,
    so tunnelled requests that merely *appear* to come from 127.0.0.1 are treated
    as remote.
    """
    ip, via_proxy = real_client_ip(headers, socket_host)
    if via_proxy:
        return False
    return _is_localhost(ip)


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
