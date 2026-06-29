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


# --- Audit/log payload redaction (REQ-42/43) -------------------------------
# A superset of secret-key detection for things that should never land in the
# persisted audit log (.governance/execution_log.json) or execution traces:
# credentials (above) plus common PII / session markers. Conservative — keyed on
# field *names*, not value heuristics, to avoid corrupting diagnostic content.
_PII_KEY_MARKERS = (
    "authorization", "cookie", "session_id", "sessionid", "ssn",
    "social_security", "credit_card", "card_number", "cvv",
)
_TRUNCATED = "***truncated***"
_MAX_STR = 2048      # cap oversized free-form values (file bodies, web pages, prompts)
_MAX_ITEMS = 100     # cap list length so a huge batch can't bloat the audit file
_MAX_DEPTH = 12      # guard against deeply nested / cyclic structures


def is_sensitive_log_key(key: str) -> bool:
    """True if a payload field name should be redacted from audit logs."""
    if is_secret_key(key):
        return True
    k = str(key).lower()
    if any(m in k for m in _PII_KEY_MARKERS):
        return True
    # "email" as a field name (but not e.g. "email_count"/"emails_total").
    if k == "email" or k.endswith("_email") or k.endswith(".email"):
        return True
    return False


def redact_payload(obj: Any, *, _depth: int = 0) -> Any:
    """Recursively redact secrets/PII and cap oversized content in a log payload.

    - dict: values under a sensitive key name → ``REDACTED``; other values recurse.
    - list/tuple: items recurse; length capped at ``_MAX_ITEMS`` with a marker.
    - str: truncated past ``_MAX_STR`` with a ``…***truncated***`` suffix.
    - depth capped so pathological/cyclic structures can't hang the writer.
    Returns a new structure; the input is not mutated.
    """
    if _depth > _MAX_DEPTH:
        return _TRUNCATED
    if isinstance(obj, dict):
        out: dict[Any, Any] = {}
        for key, val in obj.items():
            if is_sensitive_log_key(key) and val not in (None, "", [], {}):
                out[key] = REDACTED
            else:
                out[key] = redact_payload(val, _depth=_depth + 1)
        return out
    if isinstance(obj, (list, tuple)):
        items = [redact_payload(v, _depth=_depth + 1) for v in list(obj)[:_MAX_ITEMS]]
        if len(obj) > _MAX_ITEMS:
            items.append(f"{_TRUNCATED} (+{len(obj) - _MAX_ITEMS} more)")
        return items
    if isinstance(obj, str) and len(obj) > _MAX_STR:
        return obj[:_MAX_STR] + "…" + _TRUNCATED
    return obj
