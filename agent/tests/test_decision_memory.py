"""BL-235: decision memory — persist chosen + rationale + rejected alternatives."""
from __future__ import annotations

import pytest

from services.memory import decision_memory as dm


@pytest.fixture(autouse=True)
def _tmp_db(tmp_path, monkeypatch):
    monkeypatch.setattr(dm, "_db_path", lambda: tmp_path / "decisions.db")


def test_record_and_get():
    r = dm.record_decision(
        "ship the release", "reasoning", chosen_name="Reasoning-first",
        rationale="lowest risk", alternatives=[{"key": "tools", "name": "Tool-first"}],
        assumptions=["tests are green"],
    )
    assert r["ok"]
    d = dm.get_decision(r["id"])
    assert d["chosen"] == "reasoning" and d["rationale"] == "lowest risk"
    assert d["alternatives"][0]["key"] == "tools"
    assert d["assumptions"] == ["tests are green"]


def test_requires_goal_and_chosen():
    assert not dm.record_decision("", "x")["ok"]
    assert not dm.record_decision("g", "")["ok"]


def test_list_newest_first_and_project_filter():
    dm.record_decision("a", "x", project="p1")
    dm.record_decision("b", "y", project="p2")
    dm.record_decision("c", "z", project="p1")
    alld = dm.list_decisions()
    assert [d["goal"] for d in alld] == ["c", "b", "a"]
    p1 = dm.list_decisions(project="p1")
    assert {d["goal"] for d in p1} == {"a", "c"}


def test_search():
    dm.record_decision("migrate the database", "tools", rationale="use alembic")
    dm.record_decision("write docs", "reasoning", rationale="clarity first")
    assert [d["goal"] for d in dm.search_decisions("database")] == ["migrate the database"]
    assert [d["goal"] for d in dm.search_decisions("alembic")] == ["migrate the database"]


def test_deliberation_persists(monkeypatch, tmp_path):
    # run_deliberation should record a decision as a side effect
    monkeypatch.setattr(dm, "_db_path", lambda: tmp_path / "decisions.db")
    from services.planning import cognitive_workspace as cw
    monkeypatch.setattr(cw, "_generate_approaches", lambda g: [
        {"id": "A", "name": "Search-first", "key": "search"},
        {"id": "B", "name": "Reasoning-first", "key": "reasoning"},
    ])
    monkeypatch.setattr(cw, "_evaluate_approaches",
                        lambda g, a: {"chosen_id": "A", "chosen_key": "search", "rationale": "need context"})
    out = cw.run_deliberation("explore a new repo")
    assert out["chosen_key"] == "search"
    saved = dm.list_decisions()
    assert saved and saved[0]["chosen"] == "search"
    # the rejected alternative (reasoning) is retained
    assert any(alt.get("key") == "reasoning" for alt in saved[0]["alternatives"])
