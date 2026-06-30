"""Shared authentication helpers for HTTP and WebSocket endpoints.

Extracted from ``main.py`` remote_auth_middleware so that the same logic
can protect WebSocket upgrade requests.
"""
from __future__ import annotations

import hmac
import ipaddress
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


# All headers a reverse proxy / tunnel (cloudflared, ngrok, nginx) may add. A
# genuine DIRECT connection has none of them.
_FORWARD_HEADERS = ("cf-connecting-ip", "true-client-ip", "x-real-ip", "x-forwarded-for", "forwarded")
# Provider-OVERWRITE headers: cloudflare/akamai set these to the real client and
# a client behind the relay cannot forge them. Trusted unconditionally (on loopback).
_PROVIDER_HEADERS = ("cf-connecting-ip", "true-client-ip")


def _normalize_ip(raw) -> str | None:
    """Return a canonical IP string from a forwarding-header token, or None.

    Strips quotes, ``[v6]`` brackets, and a trailing ``:port`` (v4 or bracketed v6),
    then validates via ``ipaddress`` â€” so only real IPs reach the allowlist /
    rate-limit / audit sinks.
    """
    if not raw:
        return None
    s = str(raw).strip().strip('"').strip()
    if s.startswith("["):  # [::1]:port  or  [::1]
        s = s[1:].split("]", 1)[0]
    elif s.count(":") == 1 and "." in s:  # 1.2.3.4:port
        s = s.split(":", 1)[0]
    s = s.strip()
    try:
        return str(ipaddress.ip_address(s))
    except ValueError:
        return None


def _proxy_nets(trusted_proxies):
    nets = []
    for entry in (trusted_proxies or []):
        try:
            e = str(entry).strip()
            if e:
                nets.append(ipaddress.ip_network(e, strict=False))
        except ValueError:
            continue
    return nets


def _ip_in_nets(ip: str, nets) -> bool:
    try:
        addr = ipaddress.ip_address(ip)
    except ValueError:
        return False
    return any(addr in n for n in nets)


def _xff_hops(get) -> list[str]:
    """Ordered (leftâ†’right) list of normalized IPs from X-Forwarded-For + Forwarded."""
    hops: list[str] = []
    xff = get("x-forwarded-for")
    if xff:
        for part in str(xff).split(","):
            ip = _normalize_ip(part)
            if ip:
                hops.append(ip)
    fwd = get("forwarded")
    if fwd:
        for m in re.finditer(r'for=("?\[?[^;,"\]]+)', str(fwd), re.IGNORECASE):
            ip = _normalize_ip(m.group(1))
            if ip:
                hops.append(ip)
    return hops


def _load_trusted_proxies():
    try:
        import runtime_safety
        v = runtime_safety.load_config().get("tunnel_trusted_proxies")
        return v if isinstance(v, list) else []
    except Exception:
        return []


def real_client_ip(headers, socket_host: str | None, trusted_proxies=None) -> tuple[str | None, bool]:
    """Return ``(client_ip, via_proxy)``.

    Forwarding headers are honored ONLY when the request arrived on the loopback
    interface (the local tunnel terminus) â€” a direct non-loopback caller's headers
    are ignored and its socket peer is used. Within loopback:

    1. Provider-OVERWRITE headers (Cf-Connecting-Ip/True-Client-Ip) â€” unforgeable
       by a client behind the relay â€” are trusted first.
    2. X-Forwarded-For/Forwarded use **rightmost-trusted-hop**: with a configured
       ``tunnel_trusted_proxies`` list, walk rightâ†’left skipping trusted hops and
       take the first untrusted IP; without it, take the rightmost entry (the one
       the trusted loopback relay appended â€” NOT the spoofable leftmost).
    3. A forwarding header present but no usable IP â‡’ treat as remote (via_proxy)
       using the socket peer, so it must still authenticate.

    Every derived IP is validated via ``ipaddress`` before it can reach the
    allowlist / rate-limit / audit.
    """
    if not _is_localhost(socket_host):
        return socket_host, False
    get = getattr(headers, "get", None)
    if not callable(get):
        return socket_host, False

    for h in _PROVIDER_HEADERS:
        ip = _normalize_ip(get(h))
        if ip:
            return ip, True

    hops = _xff_hops(get)
    if hops:
        if trusted_proxies is None:
            trusted_proxies = _load_trusted_proxies()
        nets = _proxy_nets(trusted_proxies)
        if nets:
            for ip in reversed(hops):
                if not _ip_in_nets(ip, nets):
                    return ip, True
            return hops[0], True  # every hop trusted â‡’ leftmost is the origin client
        return hops[-1], True  # no trusted list â‡’ rightmost (relay-appended) is the client

    if any((get(h) or "").strip() for h in _FORWARD_HEADERS):
        return socket_host, True  # relayed but no parseable client IP â‡’ remote, must auth
    return socket_host, False


def require_auth_always(cfg) -> bool:
    """Effective value of the "require auth even for loopback" policy (REQ-11).

    Tri-state ``remote_require_auth_always``:
      - ``None`` (default) â‡’ **auto**: on whenever ``remote_enabled`` (so an
        exposed instance never exempts loopback by default â€” the ssh-R/socat
        header-stripping-forwarder class), off when local-only.
      - ``True``  â‡’ always require the token, even local-only.
      - ``False`` â‡’ never (explicit opt-out; loopback stays exempt even exposed).
    """
    try:
        v = cfg.get("remote_require_auth_always")
    except Exception:
        v = None
    if v is None:
        try:
            return bool(cfg.get("remote_enabled"))
        except Exception:
            return False
    return bool(v)


def is_direct_local(headers, socket_host: str | None) -> bool:
    """True only for a DIRECT loopback request (no proxy/tunnel in front).

    Use this â€” not a bare host check â€” for any "trust the local caller" decision,
    so tunnelled requests that merely *appear* to come from 127.0.0.1 are treated
    as remote.
    """
    ip, via_proxy = real_client_ip(headers, socket_host)
    if via_proxy:
        return False
    return _is_localhost(ip)
