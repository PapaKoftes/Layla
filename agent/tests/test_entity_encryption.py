"""BL-020: sensitive entity descriptions are encrypted at rest, transparent on read."""
from __future__ import annotations

import pytest

from services.memory import memory_encryption as enc

pytestmark = pytest.mark.skipif(not enc.available(), reason="cryptography not installed")

_SECRET_DESC = "lives at 42 Elm St, phone 555-0199, recovering from surgery"


def _enable(monkeypatch, on=True):
    import services.memory.memory_router as mr
    monkeypatch.setattr(mr, "_cfg", lambda: {"encryption_at_rest_enabled": on})
    # Ensure the entities table exists in the isolated test DB.
    try:
        from layla.codex.codex_db import _ensure_tables
        _ensure_tables()
    except Exception:
        pass
    enc.reset_cache()


def _raw_desc(eid):
    from layla.memory.db_connection import _conn
    with _conn() as db:
        r = db.execute("SELECT description, privacy_level FROM entities WHERE id=?", (eid,)).fetchone()
    return (r["description"], r["privacy_level"]) if r else (None, None)


def _make_entity(privacy):
    from schemas.entity import Entity
    return Entity(type="person", canonical_name="jane test doe",
                  description=_SECRET_DESC, confidence=0.9, privacy_level=privacy)


def test_sensitive_entity_description_encrypted_at_rest(monkeypatch):
    _enable(monkeypatch, True)
    from services.memory.memory_router import get_entity, upsert_entity

    ent = _make_entity("sensitive")
    assert upsert_entity(ent) is True

    raw_desc, pl = _raw_desc(ent.id)
    assert enc.is_encrypted(raw_desc), "sensitive entity description must be encrypted at rest"
    assert _SECRET_DESC not in (raw_desc or "")
    assert (pl or "").lower() == "sensitive"

    # memory_router read decrypts
    d = get_entity(ent.id)
    assert d is not None and d["description"] == _SECRET_DESC


def test_codex_read_path_decrypts(monkeypatch):
    _enable(monkeypatch, True)
    from services.memory.memory_router import upsert_entity
    ent = _make_entity("sensitive")
    assert upsert_entity(ent) is True

    # The parallel codex_db read interface must also return plaintext.
    from layla.codex.codex_db import get_entity as codex_get_entity
    d = codex_get_entity(ent.id)
    assert d is not None and d["description"] == _SECRET_DESC


def test_public_entity_description_stays_plaintext(monkeypatch):
    _enable(monkeypatch, True)
    from services.memory.memory_router import upsert_entity
    ent = _make_entity("public")
    assert upsert_entity(ent) is True
    raw_desc, _ = _raw_desc(ent.id)
    assert not enc.is_encrypted(raw_desc)
    assert raw_desc == _SECRET_DESC
