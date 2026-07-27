"""PLAN ITEM 20 / BL-020 — encryption at rest, end to end.

Covers the piece that was missing: an automatic sensitivity classifier
(`services.memory.sensitivity`) wired into the canonical learning write path
(`services.memory.memory_router.save_learning`) so that sensitive content is encrypted at rest
without a caller ever having to pass ``privacy_level="sensitive"`` by hand.

Cases:
  (a) classifier tags known-sensitive samples sensitive, ordinary learnings public
  (b) round-trip: flag ON → a sensitive learning is CIPHERTEXT at rest, PLAINTEXT read back
  (c) an ordinary learning is unencrypted AND still FTS-searchable; a sensitive one is NOT
      keyword-searchable by its plaintext (only opaque ciphertext is indexed)
  (d) key-missing degrades to plaintext with a loud one-time warning, no data loss
  (e) a pre-existing plaintext row still reads correctly (decrypt pass-through)

All DB work runs against the function-scoped `isolated_db` fixture — never the operator DB.
"""
from __future__ import annotations

import logging

import pytest

from services.memory import memory_encryption as enc
from services.memory import sensitivity

# Round-trip cases need the cipher; the classifier case (a) does not.
_needs_cipher = pytest.mark.skipif(not enc.available(), reason="cryptography not installed")

_SENSITIVE_SAMPLES = [
    "my password is hunter2primeval, do not forget it",
    "the deploy api key is sk-ABCDEF0123456789abcdef0123",
    "my social security number is 123-45-6789",
    "the patient was diagnosed with diabetes and prescribed metformin",
    "my bank account number is 12345678 and the routing number is 021000021",
    "reach me on (415) 555-0132 or at jane.doe@example.com",
    "the operator's home address is 42 plaintext lane and the gate code is 8827",
    "my passport number is X1234567 issued last year",
]

_ORDINARY_SAMPLES = [
    "the capital of France is Paris",
    "the operator prefers two-space indentation in python projects",
    "python uses indentation to define block scope",
    "we refactored the parser to use an explicit state machine",
    "the standup meeting moved to the afternoon slot",
]


def _enable(monkeypatch, on: bool = True):
    """Turn the feature flag on/off and neutralise the quality/relevance filters so the test
    exercises encryption behaviour alone (not content rejection/rewriting)."""
    import runtime_safety
    monkeypatch.setattr(
        runtime_safety,
        "load_config",
        lambda: {"encryption_at_rest_enabled": on, "learning_quality_gate_enabled": False},
    )
    import services.memory.learning_filter as lf
    monkeypatch.setattr(lf, "filter_learning", lambda content, *a, **k: (True, content, ""))
    # Reset the one-time degraded-mode warning latch so (d) can observe it deterministically.
    import services.memory.memory_router as mr
    monkeypatch.setattr(mr, "_cipher_warned", False, raising=False)
    enc.reset_cache()


def _raw_row(lid):
    """Read the row straight from SQLite, bypassing any decrypt-on-read."""
    from layla.memory.db_connection import _conn
    with _conn() as db:
        cols = [c[1] for c in db.execute("PRAGMA table_info(learnings)").fetchall()]
        sel = "content" + (", privacy_level" if "privacy_level" in cols else "")
        r = db.execute(f"SELECT {sel} FROM learnings WHERE id=?", (lid,)).fetchone()
    if not r:
        return (None, None)
    pl = r["privacy_level"] if "privacy_level" in cols else None
    return (r["content"], pl)


# ── (a) classifier ────────────────────────────────────────────────────────────

def test_classifier_flags_sensitive_and_passes_ordinary():
    for s in _SENSITIVE_SAMPLES:
        assert sensitivity.is_sensitive(s), f"should be sensitive: {s!r} (matched={sensitivity.explain(s)})"
        assert sensitivity.classify(s) == "sensitive"
    for s in _ORDINARY_SAMPLES:
        assert not sensitivity.is_sensitive(s), f"should be public: {s!r} (matched={sensitivity.explain(s)})"
        assert sensitivity.classify(s) == "public"


def test_classifier_entity_type_hook_and_empty_input():
    # A sensitive entity *type* forces sensitive even with innocuous text.
    assert sensitivity.is_sensitive("routine note", entity_type="credential")
    # Unknown/benign type falls back to content inspection.
    assert not sensitivity.is_sensitive("routine note", entity_type="technology")
    # Empty / non-string input is safe and public.
    assert sensitivity.classify("") == "public"
    assert sensitivity.classify(None) == "public"


# ── (b) round-trip ────────────────────────────────────────────────────────────

@_needs_cipher
def test_sensitive_learning_ciphertext_at_rest_plaintext_on_read(isolated_db, monkeypatch):
    _enable(monkeypatch, True)
    from services.memory.memory_router import get_recent_learnings, save_learning

    secret = "my password is hunter2primeval and my ssn is 123-45-6789"
    lid = save_learning(content=secret, kind="user_fact", confidence=0.9, source="user_command")
    assert lid and lid > 0

    raw_content, pl = _raw_row(lid)
    assert enc.is_encrypted(raw_content), "sensitive content must be ciphertext at rest"
    assert secret not in (raw_content or ""), "plaintext must never hit the DB"
    assert (pl or "").lower() == "sensitive", "row must be marked sensitive"

    # Canonical read path decrypts transparently.
    hit = next((r for r in get_recent_learnings(n=20) if r.get("id") == lid), None)
    assert hit is not None and hit["content"] == secret


@_needs_cipher
def test_high_risk_encrypts_by_default_pii_only_on_opt_in(isolated_db, monkeypatch):
    """The operator's tiered choice: HIGH-RISK (credentials/keys/passwords/gov-id) is encrypted at
    rest BY DEFAULT; broader PII (health/financial/contact) stays plaintext-and-searchable unless
    encrypt_pii_at_rest is opted in. Pins that split so a future default flip is a deliberate act."""
    from services.memory.memory_router import save_learning

    # Shipped default: encryption on, PII opt-in OFF (_enable omits encrypt_pii_at_rest → False).
    _enable(monkeypatch, True)
    hi = save_learning(content="my api key is sk-abc123def456ghi789jkl and ssn 123-45-6789",
                       kind="user_fact", confidence=0.9, source="user_command")
    pii = save_learning(content="I was diagnosed with anxiety; my email is alice@example.com",
                        kind="user_fact", confidence=0.9, source="user_command")
    hi_raw, hi_pl = _raw_row(hi)
    pii_raw, _ = _raw_row(pii)
    assert enc.is_encrypted(hi_raw) and (hi_pl or "").lower() == "sensitive", \
        "high-risk memory must be encrypted at rest by default"
    assert not enc.is_encrypted(pii_raw), "PII must stay plaintext (keyword-searchable) by default"

    # Opt in to PII encryption → now the PII memory encrypts too.
    import runtime_safety
    import services.memory.memory_router as mr
    monkeypatch.setattr(runtime_safety, "load_config", lambda: {
        "encryption_at_rest_enabled": True, "encrypt_pii_at_rest": True,
        "learning_quality_gate_enabled": False})
    monkeypatch.setattr(mr, "_cipher_warned", False, raising=False)
    pii2 = save_learning(content="my personal email is bob@example.com", kind="user_fact",
                         confidence=0.9, source="user_command")
    pii2_raw, _ = _raw_row(pii2)
    assert enc.is_encrypted(pii2_raw), "PII must encrypt at rest when encrypt_pii_at_rest is opted in"


# ── (c) ordinary stays plaintext + searchable; sensitive is not keyword-searchable ──

@_needs_cipher
def test_ordinary_plaintext_and_searchable_sensitive_not_keyword_searchable(isolated_db, monkeypatch):
    _enable(monkeypatch, True)
    from layla.memory.db import search_learnings_fts
    from services.memory.memory_router import save_learning

    ordinary = "the peregrine falcon is the fastest bird in level flight"
    oid = save_learning(content=ordinary, kind="fact", confidence=0.9, source="test")
    assert oid and oid > 0
    raw_o, pl_o = _raw_row(oid)
    assert not enc.is_encrypted(raw_o) and raw_o == ordinary
    assert (pl_o or "public") != "sensitive"

    # Non-sensitive content remains keyword-searchable via FTS/BM25.
    hits = search_learnings_fts("peregrine", n=10)
    assert any(h.get("id") == oid for h in hits), "ordinary learning must stay FTS-searchable"

    # A sensitive learning: its DISTINCTIVE plaintext keyword must NOT surface via FTS, because
    # only the opaque ciphertext is indexed (documented policy — see the FTS note below).
    secret = "the vault master password is zephyrantics and the api key is sk-QQ0011zzXY7788mmnn"
    sid = save_learning(content=secret, kind="user_fact", confidence=0.9, source="user_command")
    assert sid and sid > 0
    raw_s, pl_s = _raw_row(sid)
    assert enc.is_encrypted(raw_s)
    assert (pl_s or "").lower() == "sensitive"
    sec_hits = search_learnings_fts("zephyrantics", n=10)
    assert all(h.get("id") != sid for h in sec_hits), (
        "sensitive plaintext keyword must not be FTS-searchable (only ciphertext is indexed)"
    )


# ── (d) key-missing degrades to plaintext + warns, no data loss ───────────────

@_needs_cipher
def test_key_missing_degrades_to_plaintext_with_warning(isolated_db, monkeypatch, caplog):
    _enable(monkeypatch, True)
    # Simulate an unusable cipher/key: no Fernet can be built.
    monkeypatch.setattr(enc, "_fernet", lambda: None)
    assert enc.cipher_ready() is False

    from services.memory.memory_router import get_recent_learnings, save_learning

    secret = "my credit card number and cvv are noted here as a private credential"
    with caplog.at_level(logging.WARNING, logger="layla"):
        lid = save_learning(content=secret, kind="user_fact", confidence=0.9, source="user_command")
    assert lid and lid > 0

    raw_content, _ = _raw_row(lid)
    # Degrade to plaintext — never drop the data.
    assert not enc.is_encrypted(raw_content), "no key → must fall back to plaintext"
    assert secret in (raw_content or "")
    # And it is still readable through the app.
    hit = next((r for r in get_recent_learnings(n=20) if r.get("id") == lid), None)
    assert hit is not None and hit["content"] == secret
    # A loud warning was emitted (once).
    assert "PLAINTEXT" in caplog.text, "degraded mode must warn loudly"


# ── (e) pre-existing plaintext row reads correctly (pass-through) ─────────────

@_needs_cipher
def test_legacy_plaintext_row_reads_through_unchanged(isolated_db, monkeypatch):
    _enable(monkeypatch, True)  # cipher fully available
    from layla.memory.db import get_recent_learnings
    from layla.memory.db_connection import _conn
    from layla.time_utils import utcnow

    # A row that predates encryption: raw plaintext, no marker, inserted directly.
    legacy = "legacy note: the operator once mentioned a bank account without any protection"
    with _conn() as db:
        cur = db.execute(
            "INSERT INTO learnings (content, type, created_at, learning_type) VALUES (?,?,?,?)",
            (legacy, "fact", utcnow().isoformat(), "fact"),
        )
        db.commit()
        lid = cur.lastrowid

    raw_content, _ = _raw_row(lid)
    assert not enc.is_encrypted(raw_content), "legacy row is plaintext (no marker)"

    # decrypt() is a no-op on plaintext → the read path returns it unchanged.
    assert enc.decrypt(legacy) == legacy
    hit = next((r for r in get_recent_learnings(n=50) if r.get("id") == lid), None)
    assert hit is not None and hit["content"] == legacy
