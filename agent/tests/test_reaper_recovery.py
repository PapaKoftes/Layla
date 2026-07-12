"""audit round-2 crash-recovery cluster:
  #4 crash-reaped MISSIONS must be resumable ('paused'), not the dead-end 'interrupted'.
  #6 'queued' background tasks (whose worker thread died before starting) must also be reaped.
Background tasks stay 'interrupted' (not idempotent — no silent re-run of side effects).
"""
import sys
from pathlib import Path

AGENT_DIR = Path(__file__).resolve().parent.parent
if str(AGENT_DIR) not in sys.path:
    sys.path.insert(0, str(AGENT_DIR))


def _insert(db, table, **vals):
    """Insert a row, filling NOT NULL columns lacking a default with dummies."""
    cols = db.execute(f"PRAGMA table_info({table})").fetchall()
    row = {}
    for c in cols:
        name, ctype, notnull, dflt, pk = c[1], c[2], c[3], c[4], c[5]
        if name in vals:
            row[name] = vals[name]
        elif notnull and dflt is None and not pk:
            row[name] = 0 if "INT" in (ctype or "").upper() else ""
    keys = ",".join(row)
    qs = ",".join(["?"] * len(row))
    db.execute(f"INSERT INTO {table} ({keys}) VALUES ({qs})", tuple(row.values()))


def test_reaper_missions_paused_tasks_interrupted(isolated_db):
    from layla.memory import missions_db as md
    from layla.memory.db_connection import _conn

    with _conn() as db:
        _insert(db, "missions", id="m1", status="running")
        _insert(db, "background_tasks", id="t1", status="running")
        _insert(db, "background_tasks", id="t2", status="queued")  # never started
        db.commit()

    md.reap_orphaned_tasks()

    with _conn() as db:
        m1 = db.execute("SELECT status FROM missions WHERE id='m1'").fetchone()[0]
        t1 = db.execute("SELECT status FROM background_tasks WHERE id='t1'").fetchone()[0]
        t2 = db.execute("SELECT status FROM background_tasks WHERE id='t2'").fetchone()[0]

    # #4: a crashed mission is RESUMABLE (resume_mission_api accepts 'paused'), not a dead-end.
    assert m1 == "paused"
    # background tasks stay 'interrupted' (manual review — not idempotent).
    assert t1 == "interrupted"
    # #6: a 'queued' background task that never started is also reaped.
    assert t2 == "interrupted"


def test_reaper_paused_is_a_resumable_board_bucket():
    # #5: 'paused' has a real board bucket (so a reaped mission is no longer mislabeled 'backlog').
    import inspect

    from routers import missions as mroute
    src = inspect.getsource(mroute.mission_board_api)
    assert '"paused"' in src and 'board["paused"]' in src
