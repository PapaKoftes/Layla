"""BL-234: temporal memory timeline — chronological query + episode reconstruction."""
from __future__ import annotations

from unittest.mock import patch

import pytest

from services.memory import timeline as tl


@pytest.fixture
def isolated_db(tmp_path):
    """A fully-migrated, per-test SQLite DB.

    The shared `isolated_db` only migrates once per process (the `_MIGRATED` guard is
    reset at session scope, not per test), so a second test would get an empty DB.
    Reset the guard here so every test starts from freshly-created tables.
    """
    db_path = tmp_path / "test_layla.db"
    import layla.memory.db as db_mod
    import layla.memory.migrations as mig
    with patch("layla.memory.db._DB_PATH", db_path), \
         patch("layla.memory.db_connection._DB_PATH", db_path):
        mig._MIGRATED = False
        if hasattr(db_mod, "_MIGRATED"):
            db_mod._MIGRATED = False
        mig.migrate()
        yield db_path


def test_query_filters_and_paginates(isolated_db):
    from layla.memory import user_profile as up
    up.add_timeline_event("started project alpha", event_type="project_milestone", importance=0.9, project_id="alpha")
    up.add_timeline_event("had lunch", event_type="life_event", importance=0.2)
    up.add_timeline_event("hit a blocker", event_type="blocker", importance=0.7, project_id="alpha")

    # importance filter drops the low-signal lunch
    r = tl.query_timeline(min_importance=0.5)
    assert r["total"] == 2 and r["count"] == 2

    # project filter
    r = tl.query_timeline(project_id="alpha")
    assert r["total"] == 2

    # type filter
    r = tl.query_timeline(event_type="blocker")
    assert r["total"] == 1 and r["events"][0]["content"] == "hit a blocker"

    # pagination
    r = tl.query_timeline(limit=1, offset=0)
    assert r["count"] == 1 and r["total"] == 3


def test_days_buckets(isolated_db):
    from layla.memory import user_profile as up
    up.add_timeline_event("event one", importance=0.5)
    up.add_timeline_event("event two", importance=0.8)
    d = tl.timeline_days()
    assert d["days"] and d["days"][0]["n"] >= 2


def test_reconstruct_episode(isolated_db):
    from layla.memory import user_profile as up
    e1 = up.add_timeline_event("first thing", importance=0.6)
    e2 = up.add_timeline_event("second thing", importance=0.6)
    ep = up.create_episode("a work session")
    up.add_episode_event(ep, "milestone", str(e1), "timeline_events")
    up.add_episode_event(ep, "milestone", str(e2), "timeline_events")

    out = tl.reconstruct_episode(ep)
    assert out["ok"] and out["episode"]["summary"] == "a work session"
    assert [e["content"] for e in out["events"]] == ["first thing", "second thing"]


def test_reconstruct_missing_episode(isolated_db):
    out = tl.reconstruct_episode("nope")
    assert out["ok"] is False
