"""BL-240: proactive goal tracking — dashboard + suggestions."""
from __future__ import annotations

from unittest.mock import patch

import pytest

from services.planning import goal_tracker as gt


@pytest.fixture
def isolated_db(tmp_path):
    """Fully-migrated per-test DB (resets the once-per-process migrate guard)."""
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


def test_days_since_parses_iso():
    assert gt._days_since("") == 0.0
    assert gt._days_since("not-a-date") == 0.0


def test_dashboard_status_classification(isolated_db):
    from layla.memory import user_profile as up
    g_near = up.add_goal("almost there")
    up.add_goal_progress(g_near, "nearly", 90)
    up.add_goal("brand new")           # no progress → on_track/breakdown
    up.add_goal("also fresh")

    dash = gt.goal_dashboard()
    by_title = {g["title"]: g for g in dash["goals"]}
    assert by_title["almost there"]["status"] == "near_done"
    assert by_title["almost there"]["progress_pct"] == 90.0
    assert by_title["brand new"]["updates"] == 0
    assert dash["counts"]["total"] == 3
    assert dash["counts"]["near_done"] == 1


def test_suggestions_cover_finish_and_breakdown(isolated_db):
    from layla.memory import user_profile as up
    g = up.add_goal("ship v1")
    up.add_goal_progress(g, "close", 85)
    up.add_goal("untouched idea")

    sugg = gt.proactive_suggestions()
    kinds = {s["kind"] for s in sugg}
    assert "finish" in kinds          # 85% → finish nudge
    assert "breakdown" in kinds       # no-progress goal → breakdown nudge
    finish = next(s for s in sugg if s["kind"] == "finish")
    assert "over the line" in finish["suggestion"]


def test_initiative_hints_are_strings(isolated_db):
    from layla.memory import user_profile as up
    g = up.add_goal("polish docs")
    up.add_goal_progress(g, "almost", 95)
    hints = gt.initiative_goal_hints()
    assert hints and all(isinstance(h, str) for h in hints)
