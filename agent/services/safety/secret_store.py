"""OS-keyring-backed secret resolution (REQ-12).

Provider secrets (`tunnel_token_hash`, `*_api_key`, `*_token`, `*_secret`,
`litellm_api_keys`) should not live in plaintext in `runtime_config.json`. This
module resolves a secret-typed config value from, in priority order:

    1. the OS keyring (Windows DPAPI / macOS Keychain / Linux Secret Service via
       the `keyring` package),
    2. an environment variable ``LAYLA_<KEY_UPPER>``,
    3. the legacy plaintext value in `runtime_config.json` (back-compat fallback).

New secrets are written to the keyring (not persisted to the config file). Every
integration is a no-op when `keyring` is unavailable (`has_keyring()` is False),
so behavior is unchanged on machines without a keyring backend — the plaintext
path keeps working.
"""
from __future__ import annotations

import os

from services.safety.secret_filter import is_secret_key

_SERVICE = "layla"


def _keyring():
    try:
        import keyring  # type: ignore
        return keyring
    except Exception:
        return None


def has_keyring() -> bool:
    """True if a usable OS keyring backend is importable."""
    return _keyring() is not None


def get_secret(key: str, cfg_value=None):
    """Resolve a secret: keyring → env (``LAYLA_<KEY>``) → cfg plaintext fallback."""
    kr = _keyring()
    if kr is not None:
        try:
            v = kr.get_password(_SERVICE, key)
            if v:
                return v
        except Exception:
            pass
    env = os.environ.get("LAYLA_" + str(key).upper())
    if env:
        return env
    return cfg_value


def set_secret(key: str, value) -> bool:
    """Store (or, for empty value, delete) a secret in the keyring. Returns True
    if it was written to the keyring; False if no keyring backend is available."""
    kr = _keyring()
    if kr is None:
        return False
    try:
        if value:
            kr.set_password(_SERVICE, str(key), str(value))
        else:
            try:
                kr.delete_password(_SERVICE, str(key))
            except Exception:
                pass
        return True
    except Exception:
        return False


def resolve_config_secrets(cfg: dict) -> dict:
    """Return a copy of *cfg* with secret-typed keys resolved through the chain.

    No-op (returns *cfg* unchanged) when no keyring backend exists, so the hot
    `load_config` path pays nothing on machines without a keyring.
    """
    if not isinstance(cfg, dict) or not has_keyring():
        return cfg
    out = dict(cfg)
    for k, v in cfg.items():
        if is_secret_key(k):
            resolved = get_secret(k, v)
            if resolved is not None:
                out[k] = resolved
    return out


def persist_secret_keys(body: dict) -> tuple[dict, list[str]]:
    """Pull secret-typed keys out of a settings-save *body*, store them in the
    keyring, and return ``(body_without_persisted_secrets, stored_keys)``.

    When no keyring backend exists, returns *body* unchanged (plaintext fallback),
    so secrets keep saving exactly as before.
    """
    if not isinstance(body, dict) or not has_keyring():
        return body, []
    cleaned: dict = {}
    stored: list[str] = []
    for k, v in body.items():
        if is_secret_key(k) and v not in (None, ""):
            if set_secret(k, v):
                stored.append(k)
                continue  # do NOT persist plaintext to runtime_config.json
        cleaned[k] = v
    return cleaned, stored
