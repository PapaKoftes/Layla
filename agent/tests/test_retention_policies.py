from __future__ import annotations

from datetime import datetime, timedelta, timezone


def test_apply_retention_policies_deletes_old_rows(tmp_path, monkeypatch):
    # Isolate DB for this test explicitly (in addition to the session autouse fixture).
    data_dir = tmp_path / "layla_data"
    data_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("LAYLA_DATA_DIR", str(data_dir))

    from layla.memory.db_connection import _conn
    from layla.memory.migrations import migrate
    from services.memory_consolidation import apply_retention_policies

    migrate()
    now = datetime.now(timezone.utc)
    old = (now - timedelta(days=10)).isoformat()
    fresh = now.isoformat()

    with _conn() as db:
        # tool_outcomes: created_at based retention
        db.execute(
            "INSERT INTO tool_outcomes (tool_name, context, success, latency_ms, quality_score, created_at) VALUES (?,?,?,?,?,?)",
            ("t_old", "", 0, 0, 0.5, old),
        )
        db.execute(
            "INSERT INTO tool_outcomes (tool_name, context, success, latency_ms, quality_score, created_at) VALUES (?,?,?,?,?,?)",
            ("t_new", "", 1, 0, 0.5, fresh),
        )
        # audit: timestamp based retention
        db.execute(
            "INSERT INTO audit (timestamp, tool, args_summary, approved_by, result_ok) VALUES (?,?,?,?,?)",
            (old, "tool_old", "{}", "user", 0),
        )
        db.execute(
            "INSERT INTO audit (timestamp, tool, args_summary, approved_by, result_ok) VALUES (?,?,?,?,?)",
            (fresh, "tool_new", "{}", "user", 1),
        )
        db.commit()

    out = apply_retention_policies(
        {
            "retention_tool_outcomes_days": 1,
            "retention_audit_days": 1,
        }
    )
    assert out.get("ok") is True

    with _conn() as db:
        n_old = db.execute("SELECT COUNT(1) FROM tool_outcomes WHERE tool_name='t_old'").fetchone()[0]
        n_new = db.execute("SELECT COUNT(1) FROM tool_outcomes WHERE tool_name='t_new'").fetchone()[0]
        assert n_old == 0
        assert n_new == 1

        a_old = db.execute("SELECT COUNT(1) FROM audit WHERE tool='tool_old'").fetchone()[0]
        a_new = db.execute("SELECT COUNT(1) FROM audit WHERE tool='tool_new'").fetchone()[0]
        assert a_old == 0
        assert a_new == 1

