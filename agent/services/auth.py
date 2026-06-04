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
# a request. A genuine DIRECT connection has none of them. Provider-set headers
# (Cf-Connecting-Ip / True-Client-Ip, which the provider overwrites and a client
# cannot forge) are checked BEFORE the client-appendable X-Forwarded-For.
_FORWARD_HEADERS = ("cf-connecting-ip", "true-client-ip", "x-real-ip", "x-forwarded-for", "forwarded")


def real_client_ip(headers, socket_host: str | None) -> tuple[str | None, bool]:
    """Return ``(client_ip, via_proxy)``.

    ``via_proxy`` is True when the request was relayed by a proxy/tunnel rather
    than connecting directly. cloudflared/ngrok forward internet traffic to the
    app from 127.0.0.1, so a bare loopback-socket check would trust them; this
    flags such requests and returns the real client IP from the forwarding header.

    Forwarding headers are honored ONLY when the request actually arrived on the
    loopback interface (the local tunnel terminus). For a direct non-loopback
    connection the headers are client-spoofable, so they are ignored and the real
    socket peer is used — a LAN/internet attacker cannot fake X-Forwarded-For to
    poison the IP allowlist / rate-limit / audit.
    """
    if _is_localhost(socket_host):
        get = getattr(headers, "get", None)
        if callable(get):
            for h in _FORWARD_HEADERS:
                v = get(h)
                if v is None:
                    continue
                v = str(v).strip()
                if not v:
                    continue
                if h == "forwarded":
                    m = re.search(r'for="?\[?([^;,"\]]+)', v, re.IGNORECASE)
                    ip = (m.group(1).strip() if m else v)
                else:
                    ip = v.split(",")[0].strip()
                if ip:
                    return ip, True
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
