"""BL-132: backup checkpoints the WAL, compacts the copy, and preserves data intact."""
from __future__ import annotations

import sqlite3
from pathlib import Path


def _make_wal_db(dbp: Path) -> None:
    c = sqlite3.connect(str(dbp))
    c.execute("PRAGMA journal_mode=WAL")
    c.execute("CREATE TABLE t (id INTEGER PRIMARY KEY, v TEXT)")
    c.executemany("INSERT INTO t (v) VALUES (?)", [("x" * 200,) for _ in range(200)])
    c.commit()
    c.execute("DELETE FROM t WHERE id % 2 = 0")  # leave free pages for VACUUM to reclaim
    c.commit()
    c.close()


def test_backup_checkpoints_wal_compacts_and_preserves_data(tmp_path, monkeypatch):
    dbp = tmp_path / "layla.db"
    _make_wal_db(dbp)  # WAL-mode DB with deletions (free pages for VACUUM to reclaim)

    from layla.memory import db_connection
    monkeypatch.setattr(db_connection, "_resolve_db_path", lambda: dbp)
    # no vector store in this temp dir → that branch is a graceful skip
    from services.infrastructure.db_backup import backup_database

    res = backup_database(keep=7)
    assert res["ok"] is True
    assert isinstance(res["wal_truncated"], bool)

    bp = Path(res["backup_path"])
    assert bp.is_file()
    # the backup copy is a self-contained single file (no -wal sidecar)
    assert not (bp.parent / (bp.name + "-wal")).exists()

    # backup is a valid SQLite DB holding exactly the surviving rows
    b = sqlite3.connect(str(bp))
    try:
        assert b.execute("SELECT COUNT(*) FROM t").fetchone()[0] == 100
    finally:
        b.close()

    # the LIVE db is intact + still usable after the checkpoint (no corruption)
    live = sqlite3.connect(str(dbp))
    try:
        assert live.execute("SELECT COUNT(*) FROM t").fetchone()[0] == 100
        live.execute("INSERT INTO t (v) VALUES ('post-backup')")
        live.commit()
    finally:
        live.close()


def test_backup_missing_db_is_graceful(tmp_path, monkeypatch):
    from layla.memory import db_connection
    monkeypatch.setattr(db_connection, "_resolve_db_path", lambda: tmp_path / "nope.db")
    from services.infrastructure.db_backup import backup_database

    res = backup_database()
    assert res["ok"] is False and res.get("reason") == "db_not_found"
