"""Hardened SSRF guard — one source of truth for "is this URL safe to fetch?".

Stricter than a hostname-substring check (which several call sites used):
  - only http/https schemes (blocks file://, ftp://, gopher://, …)
  - rejects credentials embedded in the URL (user:pass@host)
  - normalizes obfuscated IPv4 (decimal 2130706433, hex 0x7f.., octal 0177..)
  - resolves hostnames via DNS and checks EVERY resolved address (DNS-rebinding)
  - blocks private / loopback / link-local / reserved / multicast / unspecified
    IPs, and IPv4-mapped IPv6 (::ffff:127.0.0.1)

Pure stdlib (urllib + socket + ipaddress) so it is unit-testable without the app.
"""
from __future__ import annotations

import ipaddress
import socket
from urllib.parse import urlsplit

_ALLOWED_SCHEMES = ("http", "https")


def _ip_is_blocked(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    # IPv4-mapped IPv6 (e.g. ::ffff:127.0.0.1) — evaluate the embedded v4.
    mapped = getattr(ip, "ipv4_mapped", None)
    if mapped is not None:
        ip = mapped
    return (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_reserved
        or ip.is_multicast
        or ip.is_unspecified
    )


def _literal_ip(host: str):
    """Return an ip address if host is an IP literal in any common encoding, else None."""
    try:
        return ipaddress.ip_address(host)
    except ValueError:
        pass
    # Obfuscated IPv4 forms (decimal / hex / octal) that inet_aton accepts.
    try:
        packed = socket.inet_aton(host)
        return ipaddress.IPv4Address(packed)
    except OSError:
        return None


def check_url(url: str, *, resolve: bool = True) -> tuple[bool, str]:
    """Return (is_safe, reason). reason is empty when safe."""
    if not url or not isinstance(url, str):
        return False, "empty url"
    try:
        parts = urlsplit(url.strip())
    except Exception as exc:
        return False, f"unparseable url: {exc}"
    if parts.scheme.lower() not in _ALLOWED_SCHEMES:
        return False, f"scheme not allowed: {parts.scheme or '(none)'}"
    if parts.username or parts.password:
        return False, "credentials in url not allowed"
    host = parts.hostname
    if not host:
        return False, "no host"
    host = host.strip("[]")

    literal = _literal_ip(host)
    if literal is not None:
        if _ip_is_blocked(literal):
            return False, f"blocked address: {literal}"
        return True, ""

    # Hostname: resolve and check every address it maps to.
    if not resolve:
        return True, ""
    try:
        infos = socket.getaddrinfo(host, None)
    except OSError as exc:
        return False, f"dns resolution failed: {exc}"
    for info in infos:
        sockaddr = info[4]
        try:
            ip = ipaddress.ip_address(sockaddr[0])
        except ValueError:
            continue
        if _ip_is_blocked(ip):
            return False, f"resolves to blocked address: {ip}"
    return True, ""


def is_safe_url(url: str, *, resolve: bool = True) -> bool:
    """Boolean convenience wrapper around check_url()."""
    ok, _ = check_url(url, resolve=resolve)
    return ok


class SSRFBlocked(PermissionError):
    """Raised by safe_urlopen when the initial URL or any redirect hop is unsafe."""


def _build_guarded_redirect_handler():
    """A urllib redirect handler that re-runs check_url on EVERY hop and vetoes an unsafe target, so a
    public URL cannot 302 into an internal/link-local host (redirect / TOCTOU SSRF). Module-level factory
    so tests can exercise the veto directly."""
    import urllib.request

    class _GuardedRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, req, fp, code, msg, hdrs, newurl):  # noqa: D401
            ok, reason = check_url(newurl)
            if not ok:
                raise SSRFBlocked(f"blocked redirect to {newurl}: {reason}")
            return super().redirect_request(req, fp, code, msg, hdrs, newurl)

    return _GuardedRedirect


def safe_urlopen(url_or_req, *, timeout: float = 30, headers: dict | None = None, data=None):
    """SSRF-safe replacement for urllib.request.urlopen.

    Validates the initial URL AND re-validates EVERY redirect hop with check_url, so a public URL
    that passes the guard cannot 302 to an internal/link-local host (redirect / TOCTOU SSRF). Accepts
    a url string or a pre-built urllib Request. Raises SSRFBlocked on any unsafe hop; urllib errors
    otherwise. Callers should route ALL outbound fetches of caller/content-supplied URLs through this.
    """
    import urllib.request

    _GuardedRedirect = _build_guarded_redirect_handler()

    if isinstance(url_or_req, urllib.request.Request):
        req = url_or_req
        if headers:
            for k, v in headers.items():
                req.add_header(k, v)
    else:
        req = urllib.request.Request(str(url_or_req), data=data, headers=headers or {})
    ok, reason = check_url(req.full_url)
    if not ok:
        raise SSRFBlocked(f"blocked url {req.full_url}: {reason}")
    opener = urllib.request.build_opener(_GuardedRedirect)
    return opener.open(req, timeout=timeout)


def safe_fetch_text(url: str, *, timeout: float = 15, headers: dict | None = None) -> str:
    """SSRF-safe drop-in for `trafilatura.fetch_url(url)`: fetches decoded body text with EVERY redirect
    hop re-validated (closes the redirect/TOCTOU gap that a plain is_safe_url + trafilatura leaves open).
    Returns '' on a blocked URL or any fetch error, so it is safe to use inside crawl/feed iteration."""
    import gzip
    import urllib.error

    h = {"User-Agent": "Mozilla/5.0 (compatible; Layla/1.0)", "Accept-Encoding": "identity"}
    if headers:
        h.update(headers)
    try:
        with safe_urlopen(url, timeout=timeout, headers=h) as resp:
            raw = resp.read()
            if str(resp.headers.get("Content-Encoding", "")).lower() == "gzip":
                try:
                    raw = gzip.decompress(raw)
                except Exception:
                    pass
            return raw.decode("utf-8", errors="replace")
    except (SSRFBlocked, urllib.error.URLError, OSError):
        return ""
