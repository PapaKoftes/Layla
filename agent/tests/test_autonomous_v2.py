import sys
from pathlib import Path

AGENT_DIR = Path(__file__).resolve().parent.parent
if str(AGENT_DIR) not in sys.path:
    sys.path.insert(0, str(AGENT_DIR))


def test_value_gate_trivial_rejects():
    from autonomous.value_gate import evaluate_value_gate

    r = evaluate_value_gate("hi")
    assert r.ok is False
    assert r.reason in ("trivial_greeting", "low_leverage", "empty_goal")


def test_value_gate_repo_audit_accepts():
    from autonomous.value_gate import evaluate_value_gate

    r = evaluate_value_gate("Fully audit the repo architecture and CI regressions across multiple files.")
    assert r.ok is True


def test_policy_blocks_non_allowlisted_tool():
    from autonomous.policy import Policy, PolicyViolation

    p = Policy(tool_allowlist=frozenset({"read_file"}), allow_network=False)
    try:
        p.validate_tool_call("write_file", {"path": "x"})
        assert False, "expected PolicyViolation"
    except PolicyViolation as e:
        assert "tool_not_allowed" in str(e)


def test_budget_steps_and_timeout_enforced(monkeypatch):
    import time

    from autonomous.budget import Budget, BudgetExceeded

    b = Budget(max_steps=1, timeout_seconds=999)
    b.consume_step()
    try:
        b.consume_step()
        assert False, "expected BudgetExceeded"
    except BudgetExceeded:
        pass

    # Timeout path: monkeypatch time.monotonic used inside Budget
    t = {"now": 0.0}

    def fake_mono():
        return t["now"]

    monkeypatch.setattr(time, "monotonic", fake_mono)
    b2 = Budget(max_steps=10, timeout_seconds=1)
    t["now"] = 0.0
    b2.consume_step()
    t["now"] = 2.0
    try:
        b2.consume_step()
        assert False, "expected BudgetExceeded"
    except BudgetExceeded:
        pass


def test_wiki_write_gated_by_allow_write(tmp_path):
    from autonomous.wiki import build_candidate, wiki_root_for_workspace, write_wiki_entry
    from layla.tools.sandbox_core import set_effective_sandbox

    set_effective_sandbox(str(tmp_path))
    try:
        cfg = {"autonomous_wiki_enabled": True}
        cand = build_candidate(title="My Topic", content_md="# Hello\n\nWorld")
        res = write_wiki_entry(workspace_root=str(tmp_path), candidate=cand, allow_write=False, cfg=cfg)
        assert res["ok"] is True
        assert res["skipped"] is True
        root = wiki_root_for_workspace(str(tmp_path))
        assert not root.exists()

        res2 = write_wiki_entry(workspace_root=str(tmp_path), candidate=cand, allow_write=True, cfg=cfg)
        assert res2["ok"] is True
        p = Path(res2["path"])
        assert p.exists()
        assert p.read_text(encoding="utf-8").strip().startswith("# Hello")
    finally:
        set_effective_sandbox(None)


def test_autonomous_router_guards(monkeypatch):
    from fastapi.testclient import TestClient

    import main
    import runtime_safety

    monkeypatch.setattr(runtime_safety, "load_config", lambda: {"autonomous_mode": False})
    client = TestClient(main.app)
    r = client.post("/autonomous/run", json={"goal": "audit", "confirm_autonomous": True})
    assert r.status_code == 403

    monkeypatch.setattr(runtime_safety, "load_config", lambda: {"autonomous_mode": True, "autonomous_max_steps": 1, "autonomous_timeout_seconds": 1})
    r2 = client.post("/autonomous/run", json={"goal": "audit"})
    assert r2.status_code == 400
    assert r2.json().get("error") == "confirm_autonomous_required"


def test_router_allow_write_follows_wiki_export_flags(monkeypatch):
    """autonomous_wiki_export_enabled gates wiki writes from POST /autonomous/run."""
    from fastapi.testclient import TestClient

    import main
    import runtime_safety
    from routers import autonomous as autonomous_router

    captured: dict[str, bool] = {}

    def capture(task, cfg, tool_call_hook=None):
        captured["allow_write"] = task.allow_write
        return {"ok": True, "source": "fresh"}

    monkeypatch.setattr(autonomous_router, "run_autonomous_task", capture)
    monkeypatch.setattr(
        runtime_safety,
        "load_config",
        lambda: {
            "autonomous_mode": True,
            "autonomous_max_steps": 10,
            "autonomous_timeout_seconds": 120,
            "autonomous_wiki_enabled": True,
            "autonomous_wiki_export_enabled": True,
        },
    )
    client = TestClient(main.app)
    goal = (
        "Fully audit the repository architecture and trace CI regressions across multiple files "
        "for coupling risks and documentation gaps."
    )
    client.post("/autonomous/run", json={"goal": goal, "confirm_autonomous": True})
    assert captured.get("allow_write") is True


def test_autonomous_router_remote_allowlist(monkeypatch):
    from fastapi.testclient import TestClient

    import main
    import runtime_safety
    from routers import autonomous as autonomous_router

    monkeypatch.setattr(autonomous_router, "_is_localhost", lambda _h: False)
    monkeypatch.setattr(
        runtime_safety,
        "load_config",
        lambda: {
            "autonomous_mode": True,
            "remote_enabled": True,
            "remote_allow_endpoints": ["/autonomous/run"],
            "remote_mode": "observe",
            "autonomous_max_steps": 1,
            "autonomous_timeout_seconds": 1,
        },
    )
    monkeypatch.setattr(autonomous_router, "run_autonomous_task", lambda **_k: {"ok": True, "stopped_reason": "test"})
    client = TestClient(main.app)
    r = client.post("/autonomous/run", json={"goal": "Fully audit the repo architecture and CI regressions across multiple files.", "confirm_autonomous": True})
    assert r.status_code == 200
    assert r.json().get("ok") is True

