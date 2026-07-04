"""Encryption-at-rest for `sensitive`-privacy memory content (BL-020).

The security-critical core: a Fernet (AES-128-CBC + HMAC) symmetric cipher whose key lives
in the OS keyring (via `secret_store`), with a documented weaker key-file fallback when no
keyring backend exists. Ciphertext carries a version marker so decryption is transparent and
any *un*-decrypted read is detectable rather than silently wrong. Every function is a graceful
no-op when encryption is disabled or the `cryptography` package is unavailable — enabling this
never breaks a machine that can't support it.

Design notes (why this is safe to layer onto existing stores):
  • `is_encrypted()` gates decrypt, so mixing plaintext (legacy rows) and ciphertext is fine.
  • Callers hash/dedup on PLAINTEXT before encrypting, so content-hash dedup is unaffected.
  • Sensitive rows must be kept OUT of any plaintext FTS index / embedding — encrypting the
    stored copy while indexing plaintext would leak it. Callers enforce that at write time.
  • Losing the key means losing the data (inherent to encryption-at-rest); the key is created
    once and persisted immediately, and we never rotate silently.
"""
from __future__ import annotations

import logging
import os
import stat
from pathlib import Path

logger = logging.getLogger("layla")

# \x00 prefix: a NUL can't occur in normal text/JSON we store, so a plaintext value can never
# be mistaken for ciphertext (and vice-versa). Bump the version if the scheme ever changes.
_MARKER = "\x00enc1:"
_KEY_NAME = "memory_encryption_key"
_fernet_cache = None  # lazily built Fernet instance (or False if unavailable)


def _fernet_cls():
    try:
        from cryptography.fernet import Fernet
        return Fernet
    except Exception:
        return None


def available() -> bool:
    """True if the `cryptography` package is importable (the feature can operate)."""
    return _fernet_cls() is not None


def _key_file() -> Path:
    """Weaker fallback location for the key when no OS keyring exists."""
    base = None
    try:
        import runtime_safety
        base = getattr(runtime_safety, "AGENT_DIR", None)
    except Exception:
        base = None
    root = Path(base) if base else (Path.home() / ".layla")
    return root / ".layla" / "memory_encryption.key"


def _load_or_create_key():
    Fernet = _fernet_cls()
    if Fernet is None:
        return None
    try:
        from services.safety import secret_store
    except Exception:
        secret_store = None

    # 1) OS keyring (preferred)
    if secret_store is not None:
        try:
            existing = secret_store.get_secret(_KEY_NAME)
            if existing:
                return existing.encode("ascii") if isinstance(existing, str) else existing
        except Exception:
            pass

    # 2) key-file fallback (weaker; only when no keyring wrote one)
    kf = _key_file()
    try:
        if kf.is_file():
            data = kf.read_bytes().strip()
            if data:
                return data
    except Exception:
        pass

    # 3) generate + persist once
    new_key = Fernet.generate_key()
    stored = False
    if secret_store is not None:
        try:
            stored = bool(secret_store.set_secret(_KEY_NAME, new_key.decode("ascii")))
        except Exception:
            stored = False
    if stored:
        return new_key
    # no keyring — persist to a 0600 key file, and warn that it's weaker
    try:
        kf.parent.mkdir(parents=True, exist_ok=True)
        kf.write_bytes(new_key)
        try:
            os.chmod(kf, stat.S_IRUSR | stat.S_IWUSR)  # 0600
        except Exception:
            pass
        logger.warning(
            "memory encryption key stored in a local file (%s) because no OS keyring is "
            "available — this is weaker than keyring storage; protect the file.", kf,
        )
        return new_key
    except Exception as e:
        logger.error("could not persist memory encryption key: %s", e)
        return None


def _fernet():
    global _fernet_cache
    if _fernet_cache is not None:
        return _fernet_cache or None
    Fernet = _fernet_cls()
    if Fernet is None:
        _fernet_cache = False
        return None
    key = _load_or_create_key()
    if not key:
        _fernet_cache = False
        return None
    try:
        _fernet_cache = Fernet(key)
    except Exception as e:
        logger.error("invalid memory encryption key: %s", e)
        _fernet_cache = False
    return _fernet_cache or None


def reset_cache() -> None:
    """Drop the cached cipher (tests / after a key change)."""
    global _fernet_cache
    _fernet_cache = None


def is_encrypted(value) -> bool:
    """True if *value* is one of our marker-prefixed ciphertexts."""
    return isinstance(value, str) and value.startswith(_MARKER)


def should_encrypt(privacy_level, cfg) -> bool:
    """Encrypt only `sensitive`-privacy content, and only when the flag is on."""
    cfg = cfg or {}
    return bool(cfg.get("encryption_at_rest_enabled")) and str(privacy_level or "").lower() == "sensitive"


def encrypt(text: str) -> str:
    """Return marker-prefixed ciphertext for *text*. No-op (returns *text*) if the value is
    empty, already encrypted, or encryption is unavailable."""
    if not isinstance(text, str) or not text or is_encrypted(text):
        return text
    f = _fernet()
    if f is None:
        return text
    try:
        return _MARKER + f.encrypt(text.encode("utf-8")).decode("ascii")
    except Exception as e:
        logger.warning("memory encrypt failed (storing plaintext): %s", e)
        return text


def decrypt(value: str) -> str:
    """Return plaintext for a marker-prefixed *value*. No-op for plaintext. If the key is gone
    or invalid, returns the value UNCHANGED (still marker-prefixed) so the failure is visible
    rather than silently corrupting data."""
    if not is_encrypted(value):
        return value
    f = _fernet()
    if f is None:
        return value
    try:
        return f.decrypt(value[len(_MARKER):].encode("ascii")).decode("utf-8")
    except Exception as e:
        logger.warning("memory decrypt failed: %s", e)
        return value


def maybe_encrypt(text, privacy_level, cfg) -> str:
    """Convenience: encrypt *text* iff should_encrypt(privacy_level, cfg)."""
    return encrypt(text) if should_encrypt(privacy_level, cfg) else text
