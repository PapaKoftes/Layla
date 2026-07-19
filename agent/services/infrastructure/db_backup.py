"""Automatic SQLite database backup using the .backup() API.

Scheduled daily by the APScheduler. Keeps the last N backups (configurable).
"""
import logging
import shutil
import time
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger("layla")

_DEFAULT_KEEP = 7  # keep last 7 backups


def backup_database(keep: int = _DEFAULT_KEEP) -> dict:
    """Create a backup of the main layla.db using SQLite's .backup() API.

    Returns dict with status and path info.
    """
    try:
        import sqlite3

        from layla.memory.db_connection import _resolve_db_path

        db_path = _resolve_db_path()
        if not db_path.exists():
            return {"ok": False, "reason": "db_not_found", "path": str(db_path)}

        backup_dir = db_path.parent / "backups"
        backup_dir.mkdir(parents=True, exist_ok=True)

        ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        backup_path = backup_dir / f"layla_{ts}.db"

        # Use SQLite .backup() API for safe hot backup
        src = sqlite3.connect(str(db_path))
        dst = sqlite3.connect(str(backup_path))
        wal_truncated = False
        try:
            # WAL checkpoint(TRUNCATE) first: fold committed WAL pages into the main file so the
            # backup is maximally fresh AND the live WAL stays bounded on a long-running DB
            # (BL-132). Best-effort — no-op in rollback-journal mode or if another writer holds it.
            try:
                row = src.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchone()
                wal_truncated = bool(row and row[0] == 0)  # busy==0 → checkpoint completed
            except Exception as we:
                logger.debug("wal_checkpoint skipped: %s", we)
            src.backup(dst)
            # VACUUM the *backup copy* (never the live DB) so stored backups are compacted —
            # reclaims free pages from deletes/erasure. Safe: operates only on backup_path.
            try:
                dst.execute("VACUUM")
            except Exception as vac:
                logger.debug("backup VACUUM skipped: %s", vac)
            logger.info("DB backup created: %s (%.1f KB)", backup_path.name, backup_path.stat().st_size / 1024)
        finally:
            dst.close()
            src.close()

        # R4: also back up the vector store (Chroma dir + the SQLite/NumPy fallback store)
        # so embeddings stay consistent with layla.db on restore — no orphaned vectors.
        vectors_backed_up = False
        try:
            # Resolver, not the raw constant: CHROMA_PATH is now None unless pinned, so the
            # location has to be asked for rather than read.
            from layla.memory.vector_store import _chroma_path
            vsrc = Path(_chroma_path())
            if vsrc.exists() and any(vsrc.iterdir()):
                shutil.copytree(str(vsrc), str(backup_dir / f"vectors_{ts}"), dirs_exist_ok=True)
                vectors_backed_up = True
                logger.info("Vector store backed up: vectors_%s", ts)
        except Exception as ve:
            logger.warning("vector-store backup skipped: %s", ve)

        # Prune old backups (both the .db files and the paired vector dirs)
        pruned = _prune_old_backups(backup_dir, keep)

        return {
            "ok": True,
            "backup_path": str(backup_path),
            "size_kb": round(backup_path.stat().st_size / 1024, 1),
            "vectors_backed_up": vectors_backed_up,
            "wal_truncated": wal_truncated,
            "pruned": pruned,
        }
    except Exception as e:
        logger.error("DB backup failed: %s", e, exc_info=True)
        return {"ok": False, "error": str(e)}


def _prune_old_backups(backup_dir: Path, keep: int) -> int:
    """Remove backups beyond the keep limit, oldest first."""
    backups = sorted(backup_dir.glob("layla_*.db"), key=lambda p: p.stat().st_mtime)
    pruned = 0
    while len(backups) > keep:
        oldest = backups.pop(0)
        try:
            oldest.unlink()
            pruned += 1
            logger.debug("Pruned old backup: %s", oldest.name)
        except Exception as e:
            logger.warning("Failed to prune backup %s: %s", oldest.name, e)
    # Prune paired vector-store dirs the same way (R4)
    vdirs = sorted(backup_dir.glob("vectors_*"), key=lambda p: p.stat().st_mtime)
    while len(vdirs) > keep:
        old = vdirs.pop(0)
        try:
            shutil.rmtree(old, ignore_errors=True)
        except Exception as e:
            logger.warning("Failed to prune vector backup %s: %s", old.name, e)
    return pruned


def list_backups() -> list[dict]:
    """Return metadata for all existing backups."""
    try:
        from layla.memory.db_connection import _resolve_db_path
        backup_dir = _resolve_db_path().parent / "backups"
        if not backup_dir.exists():
            return []
        backups = sorted(backup_dir.glob("layla_*.db"), key=lambda p: p.stat().st_mtime, reverse=True)
        return [
            {
                "name": b.name,
                "path": str(b),
                "size_kb": round(b.stat().st_size / 1024, 1),
                "created": datetime.fromtimestamp(b.stat().st_mtime, tz=timezone.utc).isoformat(),
            }
            for b in backups
        ]
    except Exception as e:
        logger.debug("list_backups failed: %s", e)
        return []
