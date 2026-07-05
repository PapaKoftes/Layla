"""BL-231: workflow recorder & macro engine — record, list, replay, params."""
from __future__ import annotations

import pytest

from services.skills import macros as mac


@pytest.fixture(autouse=True)
def _tmp_db(tmp_path, monkeypatch):
    monkeypatch.setattr(mac, "_db_path", lambda: tmp_path / "macros.db")
    # a tiny fake tool registry — record/replay both read this
    calls = []

    def _echo(**kw):
        calls.append(kw)
        return {"ok": True, "echo": kw}

    def _fail(**kw):
        return {"ok": False, "error": "boom"}

    fake = {"echo": _echo, "fail_tool": _fail}
    monkeypatch.setattr("layla.tools.registry.TOOLS", fake, raising=False)
    return calls


def test_record_and_list():
    r = mac.record_macro("greet", [{"tool": "echo", "args": {"msg": "hi"}}], description="say hi")
    assert r["ok"] and r["steps"] == 1
    lst = mac.list_macros()
    assert len(lst) == 1 and lst[0]["name"] == "greet"
    assert mac.get_macro("greet")["description"] == "say hi"


def test_reject_unknown_tool():
    r = mac.record_macro("bad", [{"tool": "nope", "args": {}}])
    assert not r["ok"] and "unknown tool" in r["error"]


def test_duplicate_name():
    mac.record_macro("dup", [{"tool": "echo", "args": {}}])
    r = mac.record_macro("dup", [{"tool": "echo", "args": {}}])
    assert not r["ok"] and "already exists" in r["error"]


def test_extract_from_run_skips_bookkeeping_and_failures():
    state = {"steps": [
        {"action": "reason", "result": {"ok": True}},
        {"action": "echo", "args": {"a": 1}, "result": {"ok": True}},
        {"action": "echo", "args": {"a": 2}, "result": {"ok": False}},  # failed → dropped
        {"action": "finish", "result": {"ok": True}},
    ]}
    steps = mac.extract_steps_from_run(state)
    assert steps == [{"tool": "echo", "args": {"a": 1}}]


def test_replay_requires_confirm():
    mac.record_macro("m", [{"tool": "echo", "args": {"x": 1}}])
    r = mac.replay_macro("m")
    assert not r["ok"] and "confirm" in r["error"]


def test_replay_runs_tools(_tmp_db):
    calls = _tmp_db
    mac.record_macro("m", [{"tool": "echo", "args": {"x": 1}}, {"tool": "echo", "args": {"x": 2}}])
    r = mac.replay_macro("m", confirm=True)
    assert r["ok"] and r["ran"] == 2
    assert calls == [{"x": 1}, {"x": 2}]
    assert mac.get_macro("m")["run_count"] == 1


def test_replay_param_substitution(_tmp_db):
    calls = _tmp_db
    r = mac.record_macro("p", [{"tool": "echo", "args": {"who": "{{name}}"}}])
    assert r["params"] == ["name"]
    mac.replay_macro("p", params={"name": "Ada"}, confirm=True)
    assert calls == [{"who": "Ada"}]


def test_replay_stops_on_error(_tmp_db):
    calls = _tmp_db
    mac.record_macro("m", [
        {"tool": "echo", "args": {"x": 1}},
        {"tool": "fail_tool", "args": {}},
        {"tool": "echo", "args": {"x": 3}},   # never reached
    ])
    r = mac.replay_macro("m", confirm=True)
    assert not r["ok"] and r["ran"] == 2
    assert calls == [{"x": 1}]


def test_replay_resolves_real_registry_shape(tmp_path, monkeypatch):
    # the real TOOLS registry maps name -> {"fn": fn, ...}, not a bare callable
    monkeypatch.setattr(mac, "_db_path", lambda: tmp_path / "m.db")
    calls = []
    real_shaped = {"echo": {"fn": lambda **kw: (calls.append(kw) or {"ok": True}), "description": "x"}}
    monkeypatch.setattr("layla.tools.registry.TOOLS", real_shaped, raising=False)
    mac.record_macro("m", [{"tool": "echo", "args": {"x": 1}}])
    r = mac.replay_macro("m", confirm=True)
    assert r["ok"] and r["ran"] == 1 and calls == [{"x": 1}]


def test_delete():
    mac.record_macro("gone", [{"tool": "echo", "args": {}}])
    assert mac.delete_macro("gone")["ok"]
    assert mac.get_macro("gone") is None
