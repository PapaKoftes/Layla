"""Shared detection + redaction of credential-bearing config keys.

Single source of truth used by endpoints that echo config back to a client
(/system_export, /settings) so secrets are never disclosed. Conservative by
design: it must not redact diagnostic keys like *_max_tokens or n_ctx.
"""
from __future__ import annotations

from typing import Any

REDACTED = "***redacted***"

_SECRET_SUBSTRINGS = ("api_key", "secret", "password", "passwd", "credential", "private_key", "passphrase")
_SECRET_TOKEN_MARKERS = ("token_hash", "bot_token", "app_token", "auth_token", "access_token", "refresh_token")


def is_secret_key(key: str) -> bool:
    """True if a config key names a credential.

    Matches credential substrings, and "token" only in clearly-credential forms
    (so "completion_max_tokens"/"tunnel_token_ttl_hours" are NOT redacted).
    """
    k = str(key).lower()
    if any(s in k for s in _SECRET_SUBSTRINGS):
        return True
    if k.endswith("_token") or any(m in k for m in _SECRET_TOKEN_MARKERS):
        return True
    return False


def redact_secrets(cfg: dict[str, Any]) -> dict[str, Any]:
    """Return a copy of cfg with credential values masked, keys preserved."""
    if not isinstance(cfg, dict):
        return cfg
    out: dict[str, Any] = {}
    for key, val in cfg.items():
        if is_secret_key(key) and val not in (None, "", [], {}):
            out[key] = REDACTED
        else:
            out[key] = val
    return out
