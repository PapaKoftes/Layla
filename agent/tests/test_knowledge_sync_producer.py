"""The KB builder must PRODUCE node-syncable knowledge rows.

`knowledge_entries` (the cluster-sync KB table) had no producer, so knowledge
cross-device sync was inert: the sync engine's ``export_since("knowledge", ...)``
always returned nothing because the table stayed empty forever. KBBuilder.save()
now persists each built article into that table, which is the exact unit node_sync
ships to paired devices. These pin the producer and prove the sync export reads it
back end-to-end (real signal — no mocks over the persist or the export).
"""
from __future__ import annotations

_LONG = (
    "FastAPI is a modern Python web framework for building APIs. "
    "It uses Pydantic for data validation and Starlette for the async web layer. "
    "It supports dependency injection and automatic OpenAPI documentation. "
) * 6


def test_kb_build_produces_syncable_knowledge_row(isolated_db, tmp_path):
    from layla.memory.db_connection import _conn
    from services.cluster.node_sync import export_since
    from services.workspace.kb_builder import build_kb_from_texts

    out = build_kb_from_texts([_LONG], topic="FastAPI", output_dir=tmp_path / "kb")
    assert out.get("ok") and out.get("articles", 0) >= 1, out

    # A durable row landed in the node-syncable table (the producer fired)...
    with _conn() as db:
        rows = db.execute("SELECT title, content FROM knowledge_entries").fetchall()
    assert rows, "KB build must produce at least one knowledge_entries row"
    assert any((r[1] or "").strip() for r in rows), "the produced row must carry content"

    # ...and the cluster sync engine actually exports it as a wire record.
    recs = export_since("knowledge", "1970-01-01T00:00:00", limit=100)
    assert recs, "node_sync must export the produced knowledge as a syncable record"
    assert any(r["kind"] == "knowledge" and (r.get("content") or "").strip() for r in recs)


def test_produced_knowledge_row_is_dedup_stable(isolated_db, tmp_path):
    """Re-building the same KB must not duplicate the syncable row (content-hash dedup)."""
    from layla.memory.db_connection import _conn
    from services.workspace.kb_builder import build_kb_from_texts

    build_kb_from_texts([_LONG], topic="FastAPI", output_dir=tmp_path / "kb1")
    with _conn() as db:
        first = db.execute("SELECT COUNT(*) FROM knowledge_entries").fetchone()[0]
    assert first >= 1

    build_kb_from_texts([_LONG], topic="FastAPI", output_dir=tmp_path / "kb2")
    with _conn() as db:
        second = db.execute("SELECT COUNT(*) FROM knowledge_entries").fetchone()[0]
    assert second == first, "identical KB content must not create duplicate syncable rows"
