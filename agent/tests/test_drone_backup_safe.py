"""Regression: drone_worker._handle_backup must produce a consistent snapshot.

Bug: _handle_backup used shutil.copy2 on the live WAL-mode layla.db, so rows
committed but not yet checkpointed (still in the -wal sidecar) were omitted from
the backup — and because it wrote the SAME backups/layla_*.db that
verify_and_recover_db restores from, a drone backup could be selected as the
newest recovery source and restore stale/torn data.

Fix: delegate to services.infrastructure.db_backup.backup_database (WAL
checkpoint(TRUNCATE) + SQLite online .backup()) so both producers of
backups/layla_*.db yield the same consistent snapshot.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path


def _make_wal_db_with_uncheckpointed_rows(dbp: Path):
    """Return an OPEN connection whose committed rows still live in the -wal file.

    Keeping the writer open (no close, no checkpoint) means a plain copy of the
    main db file would miss these rows.
    """
    c = sqlite3.connect(str(dbp))
    c.execute("PRAGMA journal_mode=WAL")
    c.execute("PRAGMA wal_autocheckpoint=0")  # never auto-fold into the main file
    c.execute("CREATE TABLE t (id INTEGER PRIMARY KEY, v TEXT)")
    c.executemany("INSERT INTO t (v) VALUES (?)", [(f"row-{i}",) for i in range(50)])
    c.commit()  # durable in the -wal sidecar, NOT yet in layla.db
    return c


def test_handle_backup_delegates_and_captures_uncheckpointed_rows(tmp_path, monkeypatch):
    dbp = tmp_path / "layla.db"
    writer = _make_wal_db_with_uncheckpointed_rows(dbp)
    try:
        from layla.memory import db_connection
        monkeypatch.setattr(db_connection, "_resolve_db_path", lambda: dbp)

        from services.cluster.drone_worker import DroneWorker
        worker = DroneWorker()
        result = worker._handle_backup({})

        assert "error" not in result, result
        bp = Path(result["backup_path"])
        assert bp.is_file()
        assert result["size_bytes"] == bp.stat().st_size

        # Consistent snapshot: all 50 committed rows are present even though they
        # were still in the -wal sidecar when the backup ran.
        b = sqlite3.connect(str(bp))
        try:
            assert b.execute("SELECT COUNT(*) FROM t").fetchone()[0] == 50
        finally:
            b.close()

        # And the backup is self-contained (no -wal sidecar left dangling).
        assert not (bp.parent / (bp.name + "-wal")).exists()
    finally:
        writer.close()


def test_handle_backup_uses_db_backup_backup_database(tmp_path, monkeypatch):
    """The drone handler must route through the safe backup_database API,
    never a raw shutil.copy2."""
    dbp = tmp_path / "layla.db"
    c = sqlite3.connect(str(dbp))
    c.execute("CREATE TABLE t (id INTEGER)")
    c.commit()
    c.close()

    from layla.memory import db_connection
    monkeypatch.setattr(db_connection, "_resolve_db_path", lambda: dbp)

    called = {"n": 0}
    from services.infrastructure import db_backup

    real = db_backup.backup_database

    def _spy(*a, **k):
        called["n"] += 1
        return real(*a, **k)

    monkeypatch.setattr(db_backup, "backup_database", _spy)

    from services.cluster.drone_worker import DroneWorker
    result = DroneWorker()._handle_backup({})

    assert called["n"] == 1, "did not delegate to db_backup.backup_database"
    assert "error" not in result, result


def test_handle_backup_missing_db_is_graceful(tmp_path, monkeypatch):
    from layla.memory import db_connection
    monkeypatch.setattr(db_connection, "_resolve_db_path", lambda: tmp_path / "nope.db")

    from services.cluster.drone_worker import DroneWorker
    result = DroneWorker()._handle_backup({})
    assert "error" in result
