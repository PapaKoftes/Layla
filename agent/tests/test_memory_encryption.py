"""BL-020: encryption-at-rest core — key management, round-trip, graceful degradation.

The pure-logic + graceful-degradation tests always run. The real-crypto tests need the
`cryptography` package (importorskip) — see tests/README.md ("encryption" feature dep).
"""
from __future__ import annotations

import pytest

from services.memory import memory_encryption as enc


@pytest.fixture(autouse=True)
def _fresh_cache():
    enc.reset_cache()
    yield
    enc.reset_cache()


def _mock_keyring(monkeypatch):
    """Simulate an OS keyring with an in-memory store so no key file is written."""
    store: dict = {}
    from services.safety import secret_store

    monkeypatch.setattr(secret_store, "get_secret", lambda k, cfg_value=None: store.get(k, cfg_value))

    def _set(k, v):
        if v:
            store[k] = v
        else:
            store.pop(k, None)
        return True

    monkeypatch.setattr(secret_store, "set_secret", _set)
    return store


# ── pure logic (no crypto needed) ──────────────────────────────────────────

def test_should_encrypt_gates_on_flag_and_level():
    on = {"encryption_at_rest_enabled": True}
    assert enc.should_encrypt("sensitive", on) is True
    assert enc.should_encrypt("SENSITIVE", on) is True           # case-insensitive
    assert enc.should_encrypt("sensitive", {"encryption_at_rest_enabled": False}) is False
    assert enc.should_encrypt("public", on) is False
    assert enc.should_encrypt("personal", on) is False
    assert enc.should_encrypt("sensitive", None) is False


def test_is_encrypted_marker():
    assert enc.is_encrypted("\x00enc1:whatever") is True
    assert enc.is_encrypted("plain text") is False
    assert enc.is_encrypted(None) is False
    assert enc.is_encrypted(123) is False


def test_graceful_without_cryptography(monkeypatch):
    monkeypatch.setattr(enc, "_fernet_cls", lambda: None)
    enc.reset_cache()
    assert enc.available() is False
    assert enc.encrypt("secret") == "secret"                     # passthrough, no crash
    assert enc.decrypt("secret") == "secret"
    assert enc.maybe_encrypt("secret", "sensitive", {"encryption_at_rest_enabled": True}) == "secret"


# ── real crypto (needs `cryptography`) ─────────────────────────────────────

pytest.importorskip("cryptography", reason="encryption-at-rest core; pip install cryptography")


def test_round_trip(monkeypatch):
    _mock_keyring(monkeypatch)
    enc.reset_cache()
    secret = "mother's maiden name is Rossi"
    ct = enc.encrypt(secret)
    assert enc.is_encrypted(ct)                                  # marker present
    assert "Rossi" not in ct                                     # plaintext not visible at rest
    assert enc.decrypt(ct) == secret                            # transparent decrypt


def test_decrypt_plaintext_passthrough(monkeypatch):
    _mock_keyring(monkeypatch)
    enc.reset_cache()
    assert enc.decrypt("just plaintext") == "just plaintext"    # legacy plaintext rows unaffected


def test_double_encrypt_is_noop(monkeypatch):
    _mock_keyring(monkeypatch)
    enc.reset_cache()
    ct = enc.encrypt("x secret y")
    assert enc.encrypt(ct) == ct                                 # already encrypted → unchanged


def test_maybe_encrypt_respects_policy(monkeypatch):
    _mock_keyring(monkeypatch)
    enc.reset_cache()
    on = {"encryption_at_rest_enabled": True}
    assert enc.is_encrypted(enc.maybe_encrypt("s", "sensitive", on))
    assert enc.maybe_encrypt("p", "public", on) == "p"          # not sensitive → plaintext
    assert enc.maybe_encrypt("s", "sensitive", {}) == "s"       # flag off → plaintext


def test_key_persists_across_cache_resets(monkeypatch):
    _mock_keyring(monkeypatch)
    enc.reset_cache()
    ct = enc.encrypt("stable across restarts")
    enc.reset_cache()                                            # simulate a fresh process
    assert enc.decrypt(ct) == "stable across restarts"          # same key loaded from keyring


def test_decrypt_with_lost_key_is_visible_not_corrupt(monkeypatch):
    store = _mock_keyring(monkeypatch)
    enc.reset_cache()
    ct = enc.encrypt("top secret")
    from cryptography.fernet import Fernet
    store["memory_encryption_key"] = Fernet.generate_key().decode()  # key rotated/lost
    enc.reset_cache()
    out = enc.decrypt(ct)
    assert out == ct and enc.is_encrypted(out)                  # unchanged + still marked → visible failure
