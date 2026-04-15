from __future__ import annotations


def test_wakeup_includes_journal_and_improvements(tmp_path, monkeypatch):
    monkeypatch.setenv("LAYLA_DB_PATH", str(tmp_path / "layla.db"))

    # Initialize shared_state for router call
    from collections import deque

    from shared_state import set_refs

    set_refs(
        history=deque(maxlen=50),
        touch_activity=lambda: None,
        read_pending=lambda: [],
        write_pending_list=lambda _x: None,
        audit_fn=lambda *_a, **_k: None,
        append_history=lambda *_a, **_k: None,
        run_autonomous_study=None,
    )

    from layla.memory.db import add_journal_entry, create_improvement

    add_journal_entry("note", "hello world")
    create_improvement("t1")

    from routers.study import wakeup

    r = wakeup()
    assert r.status_code == 200
    body = r.body.decode("utf-8")
    assert "Recent journal" in body or "journal" in body.lower()
    assert '"maturity"' in body

