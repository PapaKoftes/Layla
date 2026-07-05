"""BL-233: event-driven automation — rule CRUD, matching, dispatch."""
from __future__ import annotations

import pytest

from services.automation import rules_engine as re_


@pytest.fixture(autouse=True)
def _tmp_db(tmp_path, monkeypatch):
    monkeypatch.setattr(re_, "_db_path", lambda: tmp_path / "automation.db")


def test_add_validation():
    assert not re_.add_rule("", "file_created", "log")["ok"]
    assert not re_.add_rule("r", "bad_event", "log")["ok"]
    assert not re_.add_rule("r", "file_created", "bad_action")["ok"]
    assert re_.add_rule("r", "file_created", "log")["ok"]


def test_glob_matching():
    re_.add_rule("md-only", "file_created", "log", match_glob="*.md")
    fired = re_.dispatch_event("file_created", {"path": "/x/notes.md"})
    assert fired["fired"] == 1
    fired = re_.dispatch_event("file_created", {"path": "/x/code.py"})
    assert fired["fired"] == 0


def test_disabled_rules_dont_fire():
    r = re_.add_rule("r", "file_modified", "log")
    re_.set_enabled(r["id"], False)
    assert re_.dispatch_event("file_modified", {"path": "/a"})["fired"] == 0
    re_.set_enabled(r["id"], True)
    assert re_.dispatch_event("file_modified", {"path": "/a"})["fired"] == 1


def test_event_type_isolation():
    re_.add_rule("on-commit", "git_commit", "log")
    assert re_.dispatch_event("file_created", {})["fired"] == 0
    assert re_.dispatch_event("git_commit", {})["fired"] == 1


def test_run_macro_action(monkeypatch):
    seen = {}

    def _fake_replay(macro, params=None, confirm=False, **kw):
        seen["macro"] = macro
        seen["confirm"] = confirm
        seen["params"] = params
        return {"ok": True, "ran": 1}

    monkeypatch.setattr("services.skills.macros.replay_macro", _fake_replay, raising=False)
    re_.add_rule("build", "manual", "run_macro", params={"macro": "deploy", "params": {"env": "prod"}})
    out = re_.dispatch_event("manual", {})
    assert out["fired"] == 1 and out["results"][0]["ok"]
    assert seen == {"macro": "deploy", "confirm": True, "params": {"env": "prod"}}


def test_fire_count_and_delete():
    r = re_.add_rule("r", "manual", "log")
    re_.dispatch_event("manual", {})
    re_.dispatch_event("manual", {})
    rules = re_.list_rules()
    assert rules[0]["fire_count"] == 2
    assert re_.delete_rule(r["id"])["ok"]
    assert re_.list_rules() == []


def test_dispatch_never_raises_on_bad_action(monkeypatch):
    # a macro rule with no macro param returns ok=False but does not raise
    re_.add_rule("broken", "manual", "run_macro", params={})
    out = re_.dispatch_event("manual", {})
    assert out["fired"] == 1 and out["results"][0]["ok"] is False
