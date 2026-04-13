"""Relationship codex HTTP API."""
from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def codex_client(monkeypatch, tmp_path):
    monkeypatch.setattr("layla.tools.registry.inside_sandbox", lambda p: True)
    # Import app after monkeypatch may not work — patch on registry module used by router
    import layla.tools.registry as reg

    monkeypatch.setattr(reg, "inside_sandbox", lambda p: True)

    import main

    return TestClient(main.app), tmp_path


def test_codex_get_put_roundtrip(codex_client):
    client, root = codex_client
    root.mkdir(parents=True, exist_ok=True)
    q = f"?workspace_root={root.as_posix()}"
    r = client.get(f"/codex/relationship{q}")
    assert r.status_code == 200
    j = r.json()
    assert j.get("ok") is True
    assert j.get("data", {}).get("entities") == {}

    data = {"entities": {"ahmed": {"traits": ["colleague"], "notes": "Works on API"}}}
    r2 = client.put(f"/codex/relationship{q}", json=data)
    assert r2.status_code == 200
    assert r2.json().get("ok") is True

    r3 = client.get(f"/codex/relationship{q}")
    assert r3.json().get("data", {}).get("entities", {}).get("ahmed", {}).get("notes") == "Works on API"


def test_codex_rejects_outside_sandbox(monkeypatch, tmp_path):
    import layla.tools.registry as reg

    monkeypatch.setattr(reg, "inside_sandbox", lambda p: False)
    import main

    client = TestClient(main.app)
    r = client.get(f"/codex/relationship?workspace_root={tmp_path.as_posix()}")
    assert r.status_code == 400
    assert "sandbox" in (r.json().get("error") or "").lower()


def test_format_codex_prompt_digest():
    from services.relationship_codex import format_codex_prompt_digest

    assert format_codex_prompt_digest({}, 500) == ""
    d = {"entities": {"x": {"traits": ["a", "b"], "notes": "hello"}}}
    s = format_codex_prompt_digest(d, max_chars=500)
    assert "x" in s
    assert "hello" in s or "traits" in s


def test_codex_injection_respects_cap():
    from services.relationship_codex import format_codex_prompt_digest

    entities = {f"e{i}": {"traits": ["t"], "notes": "x" * 200} for i in range(30)}
    d = {"entities": entities}
    out = format_codex_prompt_digest(d, max_chars=280)
    assert len(out) <= 400
    assert out.count("\n") >= 1 or len(out) < 280


def test_codex_not_injected_outside_sandbox(monkeypatch, tmp_path):
    import agent_loop
    import runtime_safety

    monkeypatch.setattr("layla.tools.registry.inside_sandbox", lambda p: False)
    cfg = {
        "relationship_codex_inject_enabled": True,
        "relationship_codex_inject_max_chars": 500,
    }
    block, active = agent_loop._relationship_codex_context(cfg, str(tmp_path))
    assert block == ""
    assert active is False


def test_codex_injected_when_sandbox_and_entities(monkeypatch, tmp_path):
    import agent_loop

    monkeypatch.setattr("layla.tools.registry.inside_sandbox", lambda p: True)
    root = tmp_path / "proj"
    root.mkdir()
    layla = root / ".layla"
    layla.mkdir()
    (layla / "relationship_codex.json").write_text(
        '{"entities": {"sam": {"traits": ["friend"], "notes": "met at conf"}}}',
        encoding="utf-8",
    )
    cfg = {"relationship_codex_inject_enabled": True, "relationship_codex_inject_max_chars": 800}
    block, active = agent_loop._relationship_codex_context(cfg, str(root))
    assert active is True
    assert "sam" in block
    assert "Relationship codex" in block


def test_decision_bias_extension_includes_codex_line():
    import orchestrator

    out = orchestrator.decision_bias_prompt_extension([], relationship_codex_active=True)
    assert "Relationship codex is active" in out


def test_codex_suggest_update_tool_read_only(tmp_path, monkeypatch):
    monkeypatch.setattr("layla.tools.registry.inside_sandbox", lambda p: True)
    from layla.tools import registry as reg

    monkeypatch.setattr(reg, "inside_sandbox", lambda p: True)
    root = tmp_path / "w"
    root.mkdir()
    (root / ".layla").mkdir()
    (root / ".layla" / "relationship_codex.json").write_text('{"entities":{}}', encoding="utf-8")
    r = reg.codex_suggest_update(str(root), goal_hint="Ahmed prefers email")
    assert r.get("ok") is True
    assert r.get("read_only") is True
    assert isinstance(r.get("suggestions"), list)
