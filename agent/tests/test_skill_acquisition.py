"""BL-238: skill acquisition — learn an executable skill from a successful run."""
from __future__ import annotations

import pytest

from services.skills import macros as mac
from services.skills import skill_acquisition as sa


@pytest.fixture(autouse=True)
def _tmp(tmp_path, monkeypatch):
    monkeypatch.setattr(sa, "_db_path", lambda: tmp_path / "learned.db")
    monkeypatch.setattr(mac, "_db_path", lambda: tmp_path / "macros.db")
    calls = []

    def _echo(**kw):
        calls.append(kw)
        return {"ok": True, "echo": kw}

    monkeypatch.setattr("layla.tools.registry.TOOLS", {"read_file": _echo, "grep_code": _echo}, raising=False)
    return calls


_RUN = {
    "original_goal": "find the port in the config",
    "steps": [
        {"action": "think", "result": {"ok": True, "thought": "look at config"}},
        {"action": "read_file", "args": {"path": "cfg.json"}, "result": {"ok": True}},
        {"action": "grep_code", "args": {"q": "port"}, "result": {"ok": True}},
        {"action": "reason", "result": "the port is 8080"},
    ],
}


def test_suggest_name_drops_stopwords():
    assert sa.suggest_name("find the port in the config") == "find-port-config"


def test_acquire_and_list():
    r = sa.acquire_from_run(_RUN)
    assert r["ok"] and r["steps"] == 2 and r["name"] == "find-port-config"
    skills = sa.list_learned_skills()
    assert len(skills) == 1 and skills[0]["macro_name"] == "skill:find-port-config"
    # the backing macro exists
    assert mac.get_macro("skill:find-port-config") is not None


def test_acquire_requires_min_steps():
    thin = {"original_goal": "g", "steps": [{"action": "read_file", "args": {}, "result": {"ok": True}}]}
    assert not sa.acquire_from_run(thin)["ok"]


def test_invoke_replays(_tmp):
    calls = _tmp
    sa.acquire_from_run(_RUN, name="portfinder")
    # without confirm → no execution
    r = sa.invoke_skill("portfinder")
    assert not r["ok"]
    assert calls == []
    # with confirm → runs both tool steps
    r = sa.invoke_skill("portfinder", confirm=True)
    assert r["ok"] and r["ran"] == 2
    assert len(calls) == 2
    assert sa.get_learned_skill("portfinder")["use_count"] == 1


def test_forget_removes_skill_and_macro():
    sa.acquire_from_run(_RUN, name="tmp")
    assert sa.forget_skill("tmp")["ok"]
    assert sa.get_learned_skill("tmp") is None
    assert mac.get_macro("skill:tmp") is None


def test_duplicate_name_rejected():
    sa.acquire_from_run(_RUN, name="dup")
    assert not sa.acquire_from_run(_RUN, name="dup")["ok"]
