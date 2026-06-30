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
