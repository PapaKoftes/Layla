"""
tunnel_auth.py — Dedicated auth module for Layla's remote-access tunnel.

Extracts and enhances the inline Bearer-token auth from main.py middleware
into a proper system with hashed storage, token rotation, IP allowlisting,
and configurable expiry.

Config keys (runtime_safety.py / runtime_config.json):
    remote_api_key          — legacy plaintext token (backward compat, deprecated)
    tunnel_token_hash       — SHA-256 hex digest of the active token
    tunnel_token_created_at — ISO-8601 timestamp of token generation
    tunnel_token_ttl_hours  — 0 = never expire, >0 = hours until expiry
    tunnel_ip_allowlist     — list of allowed IPs/CIDRs (empty = all allowed)
"""

from __future__ import annotations

import hashlib
import ipaddress
import logging
import secrets
from datetime import datetime, timezone
from typing import Tuple

logger = logging.getLogger("layla")


# ---------------------------------------------------------------------------
# Token generation
# ---------------------------------------------------------------------------

def generate_token() -> str:
    """Generate a cryptographically secure URL-safe token (43 chars, 256 bits)."""
    return secrets.token_urlsafe(32)


# ---------------------------------------------------------------------------
# Token hashing
# ---------------------------------------------------------------------------

def hash_token(token: str) -> str:
    """Return the SHA-256 hex digest of *token*.

    Tokens are never stored in plaintext; only this hash is persisted in
    ``tunnel_token_hash``.
    """
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# Token validation
# ---------------------------------------------------------------------------

def validate_token(token: str, cfg: dict) -> Tuple[bool, str]:
    """Validate a raw Bearer *token* against the stored hash (or legacy key).

    Checks in order:
        1. ``tunnel_token_hash`` — preferred (constant-time comparison via
           :func:`hmac.compare_digest`).
        2. ``remote_api_key``   — legacy plaintext fallback (backward compat).

    Returns:
        ``(True, "")`` on success, ``(False, reason)`` on failure.
    """
    if not token or not token.strip():
        return False, "missing_token"

    token = token.strip()

    # -- new-style: compare hashes ------------------------------------------
    stored_hash = (cfg.get("tunnel_token_hash") or "").strip()
    if stored_hash:
        import hmac
        candidate_hash = hash_token(token)
        if hmac.compare_digest(candidate_hash, stored_hash):
            return True, ""
        # Hash present but didn't match — still try legacy below so that
        # operators who set both aren't locked out during migration.

    # -- legacy: plaintext remote_api_key -----------------------------------
    legacy_key = cfg.get("remote_api_key")
    if legacy_key and str(legacy_key).strip():
        import hmac
        if hmac.compare_digest(token, str(legacy_key).strip()):
            logger.warning(
                "tunnel_auth: token matched via legacy remote_api_key — "
                "migrate to tunnel_token_hash for better security"
            )
            return True, ""

    if stored_hash or (legacy_key and str(legacy_key).strip()):
        return False, "invalid_token"
    return False, "no_token_configured"


# ---------------------------------------------------------------------------
# Token rotation
# ---------------------------------------------------------------------------

def rotate_token(cfg: dict) -> Tuple[str, str]:
    """Generate a new token and return ``(new_token, new_hash)``.

    The caller is responsible for persisting the hash and timestamp::

        token, hashed = rotate_token(cfg)
        cfg["tunnel_token_hash"] = hashed
        cfg["tunnel_token_created_at"] = datetime.now(timezone.utc).isoformat()
        save_config(cfg)

    The plaintext token should be shown to the operator *once* and never stored.
    """
    new_token = generate_token()
    new_hash = hash_token(new_token)
    logger.info("tunnel_auth: token rotated — new hash starts with %s…", new_hash[:8])
    return new_token, new_hash


# ---------------------------------------------------------------------------
# IP allowlist
# ---------------------------------------------------------------------------

def is_ip_allowed(ip: str, cfg: dict) -> bool:
    """Check whether *ip* is permitted by ``tunnel_ip_allowlist``.

    Rules:
        - If the allowlist is empty or absent, **all** IPs are allowed.
        - Each entry may be a bare IP (``"192.168.1.10"``) or a CIDR
          (``"10.0.0.0/8"``).
        - Returns ``True`` if *ip* matches any entry.
    """
    allowlist = cfg.get("tunnel_ip_allowlist") or []
    if not allowlist:
        return True  # empty = all allowed

    if not ip:
        return False

    # Localhost is always allowed regardless of allowlist
    _LOCALHOST = {"127.0.0.1", "::1", "::ffff:127.0.0.1", "localhost"}
    if ip.strip().lower() in _LOCALHOST:
        return True

    try:
        addr = ipaddress.ip_address(ip)
    except ValueError:
        logger.warning("tunnel_auth: could not parse client IP %r", ip)
        return False

    for entry in allowlist:
        try:
            entry = str(entry).strip()
            if "/" in entry:
                network = ipaddress.ip_network(entry, strict=False)
                if addr in network:
                    return True
            else:
                if addr == ipaddress.ip_address(entry):
                    return True
        except ValueError:
            logger.warning("tunnel_auth: invalid allowlist entry %r — skipping", entry)
            continue

    return False


# ---------------------------------------------------------------------------
# Token expiry
# ---------------------------------------------------------------------------

def is_token_expired(cfg: dict) -> bool:
    """Return ``True`` if the active token has exceeded its TTL.

    Uses ``tunnel_token_created_at`` (ISO-8601) and ``tunnel_token_ttl_hours``.
    A TTL of 0 (the default) means the token never expires.
    Returns ``False`` when expiry info is absent (backward compat).
    """
    ttl_hours = cfg.get("tunnel_token_ttl_hours", 0)
    if not ttl_hours or ttl_hours <= 0:
        return False  # 0 or negative = never expires

    created_at_str = cfg.get("tunnel_token_created_at")
    if not created_at_str:
        # No creation timestamp — cannot determine expiry; treat as not expired
        # so we don't lock out operators who haven't rotated yet.
        return False

    try:
        created_at = datetime.fromisoformat(str(created_at_str))
        # Ensure timezone-aware (assume UTC if naive)
        if created_at.tzinfo is None:
            created_at = created_at.replace(tzinfo=timezone.utc)
        now = datetime.now(timezone.utc)
        elapsed_hours = (now - created_at).total_seconds() / 3600.0
        if elapsed_hours > ttl_hours:
            logger.info(
                "tunnel_auth: token expired (%.1fh elapsed, TTL=%dh)",
                elapsed_hours,
                ttl_hours,
            )
            return True
        return False
    except (ValueError, TypeError) as exc:
        logger.warning("tunnel_auth: could not parse tunnel_token_created_at: %s", exc)
        return False


# ---------------------------------------------------------------------------
# Combined check
# ---------------------------------------------------------------------------

def check_remote_access(token: str, ip: str, cfg: dict) -> Tuple[bool, str]:
    """Full remote-access gate: token + IP allowlist + expiry.

    Returns:
        ``(True, "")`` if the request is authorised.
        ``(False, reason)`` if denied, where *reason* is a short machine-readable
        string (e.g. ``"invalid_token"``, ``"ip_denied"``, ``"token_expired"``).
    """
    # 1. IP allowlist (check first — cheapest, avoids leaking token info)
    if not is_ip_allowed(ip, cfg):
        logger.warning("tunnel_auth: denied — IP %s not in allowlist", ip)
        return False, "ip_denied"

    # 2. Token expiry
    if is_token_expired(cfg):
        return False, "token_expired"

    # 3. Token validation
    ok, reason = validate_token(token, cfg)
    if not ok:
        logger.warning("tunnel_auth: denied — %s (IP=%s)", reason, ip)
        return False, reason

    return True, ""
