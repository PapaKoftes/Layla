"""BL-020: sensitive learnings are encrypted at rest, transparent on read, kept out of embeddings/ES."""
from __future__ import annotations

import pytest

from services.memory import memory_encryption as enc

pytestmark = pytest.mark.skipif(not enc.available(), reason="cryptography not installed")

_SECRET = "my bank PIN is 4457 and my SSN is 123-45-6789"


def _raw_row(lid):
    from layla.memory.db_connection import _conn
    with _conn() as db:
        cols = [c[1] for c in db.execute("PRAGMA table_info(learnings)").fetchall()]
        sel = "content, embedding_id" + (", privacy_level" if "privacy_level" in cols else "")
        r = db.execute(f"SELECT {sel} FROM learnings WHERE id=?", (lid,)).fetchone()
    if not r:
        return (None, None, None)
    pl = r["privacy_level"] if "privacy_level" in cols else None
    return (r["content"], r["embedding_id"], pl)


def _enable(monkeypatch, on=True):
    import runtime_safety
    monkeypatch.setattr(runtime_safety, "load_config", lambda: {"encryption_at_rest_enabled": on})
    # Isolate encryption behavior from the quality filter (which can reject/rewrite content).
    import services.memory.learning_filter as lf
    monkeypatch.setattr(lf, "filter_learning", lambda content, *a, **k: (True, content, ""))
    enc.reset_cache()


def test_sensitive_learning_is_encrypted_at_rest(monkeypatch):
    _enable(monkeypatch, True)
    from layla.memory.learnings import get_recent_learnings, save_learning

    lid = save_learning(_SECRET, kind="fact", privacy_level="sensitive", source="test")
    assert lid and lid > 0

    raw_content, raw_eid, pl = _raw_row(lid)
    # Stored ciphertext carries the marker — the plaintext never hits the DB.
    assert enc.is_encrypted(raw_content), "sensitive content must be encrypted at rest"
    assert _SECRET not in (raw_content or "")
    # Never embedded (an embedding vector would leak the meaning).
    assert not raw_eid, "sensitive learning must not be embedded"
    assert (pl or "").lower() == "sensitive", "privacy_level must be persisted to the column"

    # Reads transparently decrypt back to plaintext.
    recents = get_recent_learnings(n=10)
    hit = next((r for r in recents if r.get("id") == lid), None)
    assert hit is not None and hit["content"] == _SECRET


def test_non_sensitive_learning_stays_plaintext(monkeypatch):
    _enable(monkeypatch, True)
    from layla.memory.learnings import save_learning

    lid = save_learning("just an ordinary fact about pandas", kind="fact", source="test")
    raw_content, _, _ = _raw_row(lid)
    assert not enc.is_encrypted(raw_content)
    assert raw_content == "just an ordinary fact about pandas"


def test_flag_off_stores_plaintext_even_if_marked_sensitive(monkeypatch):
    # The privacy tag alone does nothing unless the feature flag is on.
    _enable(monkeypatch, False)
    from layla.memory.learnings import save_learning

    lid = save_learning("flag is off " + _SECRET, kind="fact", privacy_level="sensitive", source="test")
    raw_content, _, _ = _raw_row(lid)
    assert not enc.is_encrypted(raw_content)


def test_legacy_plaintext_still_readable_after_enabling(monkeypatch):
    # A row written as plaintext (flag off) must still read fine once encryption is enabled
    # (decrypt is a no-op on plaintext — mixed rows coexist).
    _enable(monkeypatch, False)
    from layla.memory.learnings import get_recent_learnings, save_learning
    lid = save_learning("legacy plaintext row about rivers", kind="fact", source="test")
    _enable(monkeypatch, True)
    recents = get_recent_learnings(n=20)
    hit = next((r for r in recents if r.get("id") == lid), None)
    assert hit is not None and hit["content"] == "legacy plaintext row about rivers"
