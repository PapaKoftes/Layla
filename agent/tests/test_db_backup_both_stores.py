"""R4: backup_database backs up BOTH the SQLite db AND the vector store, so a restore
keeps embeddings consistent with the record-of-truth (no orphaned vectors)."""
import sqlite3
import sys
from pathlib import Path

AGENT_DIR = Path(__file__).resolve().parent.parent
if str(AGENT_DIR) not in sys.path:
    sys.path.insert(0, str(AGENT_DIR))


def test_backup_covers_db_and_vectors(tmp_path, monkeypatch):
    # fake SQLite db
    db = tmp_path / "layla.db"
    con = sqlite3.connect(str(db))
    con.execute("CREATE TABLE t(x)")
    con.commit()
    con.close()
    # fake vector store dir with content
    vdir = tmp_path / "chroma_db"
    vdir.mkdir()
    (vdir / "fallback_learnings.sqlite").write_bytes(b"vec-data")

    import layla.memory.db_connection as dbc
    import layla.memory.vector_store as vs
    monkeypatch.setattr(dbc, "_resolve_db_path", lambda: db)
    monkeypatch.setattr(vs, "CHROMA_PATH", vdir)

    from services.infrastructure.db_backup import backup_database
    res = backup_database(keep=5)

    assert res["ok"] is True
    assert res["vectors_backed_up"] is True
    backups = tmp_path / "backups"
    assert list(backups.glob("layla_*.db")), "db backup missing"
    vbk = list(backups.glob("vectors_*"))
    assert vbk and (vbk[0] / "fallback_learnings.sqlite").exists(), "vector backup missing"


def test_backup_ok_when_no_vectors(tmp_path, monkeypatch):
    db = tmp_path / "layla.db"
    con = sqlite3.connect(str(db))
    con.execute("CREATE TABLE t(x)")
    con.commit()
    con.close()
    import layla.memory.db_connection as dbc
    import layla.memory.vector_store as vs
    monkeypatch.setattr(dbc, "_resolve_db_path", lambda: db)
    monkeypatch.setattr(vs, "CHROMA_PATH", tmp_path / "does_not_exist")
    from services.infrastructure.db_backup import backup_database
    res = backup_database(keep=5)
    assert res["ok"] is True and res["vectors_backed_up"] is False
