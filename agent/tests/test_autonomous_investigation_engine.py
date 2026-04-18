import json
import sys
from pathlib import Path
from typing import Any

AGENT_DIR = Path(__file__).resolve().parent.parent
if str(AGENT_DIR) not in sys.path:
    sys.path.insert(0, str(AGENT_DIR))


def test_value_gate_rejects_direct_action():
    from autonomous.value_gate import evaluate_value_gate

    r = evaluate_value_gate("run pytest and fix all failures in the repo")
    assert r.ok is False
    assert r.reason == "direct_action_use_agent"


def test_value_gate_rejects_short_single_step():
    from autonomous.value_gate import evaluate_value_gate

    r = evaluate_value_gate("what is a list")
    assert r.ok is False


def test_value_gate_accepts_investigation():
    from autonomous.value_gate import evaluate_value_gate

    r = evaluate_value_gate(
        "Audit the repository architecture, trace the agent request path, and list CI regression risks across multiple files."
    )
    assert r.ok is True


def test_context_read_dedupe_same_path(tmp_path):
    from autonomous.context import ContextState

    fake = {"ok": True, "content": "hello"}
    ctx = ContextState(goal="test")
    p = str(tmp_path / "a.txt")
    ctx.record_read_file_result({"path": p}, fake)
    d = ctx.dedupe_file_reads(p)
    assert d is not None
    assert d.get("_deduped_read") is True


def test_aggregate_structured_contract():
    from autonomous.aggregator import aggregate
    from autonomous.types import PlannerDecision, StepRecord

    fd = {
        "summary": "Done",
        "reasoning": "Because",
        "confidence": "high",
        "findings": [{"insight": "A", "evidence": ["f.py:1"]}],
        "next_steps": [{"action": "patch", "tool": "write_file", "reason": "fix", "confidence": "low"}],
    }
    steps = [
        StepRecord(
            i=0,
            decision=PlannerDecision(type="final", final=fd),
            tool_ok=True,
            tool_result=fd,
        )
    ]
    out = aggregate(
        goal="g",
        steps=steps,
        value_gate={"ok": True},
        stopped_reason="planner_final",
        files_accessed=["/x/a.py"],
    )
    assert out["confidence"] == "high"
    assert len(out["findings"]) == 1
    assert out["findings"][0]["insight"] == "A"
    assert out["findings"][0]["evidence"] == ["f.py:1"]
    assert out["next_steps"][0]["tool"] == "write_file"
    assert out["proposed_actions"] == out["next_steps"]
    assert out.get("source") == "fresh"
    assert out.get("reused") is False
    assert out["investigation_engine"] is True
    assert "/x/a.py" in out["files_accessed"]


def test_controller_rejects_disallowed_tool(monkeypatch):
    """Non–Tier-0 tools must fail at policy before any TOOLS invocation."""
    from autonomous.controller import run_autonomous_task
    from autonomous.types import AutonomousTask, PlannerDecision

    def fake_decide(self, *, goal, context, budget_hint):
        return PlannerDecision(type="tool", tool="write_file", args={})

    monkeypatch.setattr("autonomous.controller.Planner.decide", fake_decide)
    task = AutonomousTask(
        goal="Trace authentication flow across services and summarize regression risks in the codebase.",
        workspace_root=".",
        max_steps=5,
        timeout_seconds=30,
        confirm_autonomous=True,
    )
    out = run_autonomous_task(task=task, cfg={}, tool_call_hook=None)
    assert out.get("stopped_reason") == "policy_violation"
    assert any("tool_not_allowed" in str(x) for x in (out.get("tool_errors") or []))


def test_budget_exceeded_endless_tool_loop(monkeypatch, tmp_path):
    """Planner never emits final; controller exhausts step budget."""
    from autonomous.controller import run_autonomous_task
    from autonomous.types import AutonomousTask, PlannerDecision
    from layla.tools.sandbox_core import set_effective_sandbox

    fp = tmp_path / "note.txt"
    fp.write_text("hello", encoding="utf-8")
    set_effective_sandbox(str(tmp_path))
    try:

        def fake_decide(self, *, goal, context, budget_hint):
            return PlannerDecision(type="tool", tool="read_file", args={"path": str(fp)})

        monkeypatch.setattr("autonomous.controller.Planner.decide", fake_decide)
        task = AutonomousTask(
            goal=(
                "Investigate this codebase: trace how configuration is loaded across modules, "
                "map dependencies, and summarize regression risks across multiple files."
            ),
            workspace_root=str(tmp_path),
            max_steps=3,
            timeout_seconds=300,
            confirm_autonomous=True,
        )
        out = run_autonomous_task(task=task, cfg={}, tool_call_hook=None)
        assert out["stopped_reason"] == "budget_exceeded"
        assert out.get("budget_detail") == "steps"
        assert out["steps_used"] == 3
        assert len(out.get("files_accessed") or []) == 1
    finally:
        set_effective_sandbox(None)


def test_aggregate_normalizes_budget_stop_reason():
    from autonomous.aggregator import aggregate
    from autonomous.types import PlannerDecision, StepRecord

    steps = [
        StepRecord(i=0, decision=PlannerDecision(type="tool", tool="read_file", args={}, attempts_used=1))
    ]
    out = aggregate(
        goal="g",
        steps=steps,
        value_gate={"ok": True},
        stopped_reason="max_steps_loop_end",
        files_accessed=None,
    )
    assert out["stopped_reason"] == "budget_exceeded"
    assert out.get("budget_detail") == "steps"


def test_confidence_basis_reflects_evidence(monkeypatch):
    from autonomous.aggregator import aggregate
    from autonomous.types import PlannerDecision, StepRecord

    fd_weak = {"summary": "x", "confidence": "medium", "findings": [{"insight": "a", "evidence": []}]}
    fd_strong = {
        "summary": "x",
        "confidence": "medium",
        "findings": [
            {"insight": "a", "evidence": ["f.py:1"]},
            {"insight": "b", "evidence": ["g.py:2"]},
        ],
    }
    base = dict(
        goal="g",
        steps=[
            StepRecord(i=0, decision=PlannerDecision(type="final", final=fd_weak), tool_ok=True),
        ],
        value_gate={"ok": True},
        stopped_reason="planner_final",
        files_accessed=["/a.py", "/b.py", "/c.py"],
    )
    out_weak = aggregate(**base)
    base["steps"] = [
        StepRecord(i=0, decision=PlannerDecision(type="final", final=fd_strong), tool_ok=True),
    ]
    base["files_accessed"] = ["/a.py", "/b.py", "/c.py"]
    out_strong = aggregate(**base)
    basis_w = out_weak.get("confidence_basis") or {}
    basis_s = out_strong.get("confidence_basis") or {}
    assert basis_w.get("findings_with_evidence", 0) == 0
    assert basis_s.get("findings_with_evidence", 0) >= 2
    assert basis_s.get("files_boost") is True
    assert basis_w.get("files_boost") is True


def test_cross_run_read_cache_put_get(tmp_path):
    from autonomous.read_cache import CrossRunReadCache

    fp = tmp_path / "cached.txt"
    fp.write_text("payload", encoding="utf-8")
    c = CrossRunReadCache(max_entries=32)
    assert c.get(str(fp)) is None
    c.put(str(fp), {"ok": True, "content": "payload"})
    hit = c.get(str(fp))
    assert isinstance(hit, dict) and hit.get("content") == "payload"


def test_investigation_reuse_jsonl(tmp_path):
    from autonomous.investigation_reuse import maybe_append_investigation_reuse

    cfg = {"investigation_reuse_store_enabled": True}
    r = maybe_append_investigation_reuse(
        cfg=cfg,
        workspace_root=str(tmp_path),
        goal="Audit the repo across modules for coupling risks.",
        summary="Summary text",
        findings=[{"insight": "x", "evidence": ["a.py:1"]}],
        confidence="high",
        run_id="test-run",
    )
    assert r and r.get("ok")
    p = tmp_path / ".layla" / "investigation_reuse.jsonl"
    assert p.exists()
    assert "Summary text" in p.read_text(encoding="utf-8")


def test_investigation_reuse_skips_non_high(tmp_path):
    from autonomous.investigation_reuse import maybe_append_investigation_reuse

    cfg = {"investigation_reuse_store_enabled": True}
    r = maybe_append_investigation_reuse(
        cfg=cfg,
        workspace_root=str(tmp_path),
        goal="g",
        summary="s",
        findings=[],
        confidence="medium",
    )
    assert r is None


def test_aggregate_includes_investigation_trace():
    from autonomous.aggregator import aggregate
    from autonomous.types import PlannerDecision, StepRecord

    steps = [
        StepRecord(
            i=0,
            decision=PlannerDecision(type="tool", tool="grep_code", args={}, attempts_used=1),
            tool_ok=True,
            tool_result={"ok": True, "matches": ["m1"]},
        ),
        StepRecord(
            i=1,
            decision=PlannerDecision(type="final", final={"summary": "S", "reasoning": "R", "confidence": "medium"}),
            tool_ok=True,
        ),
    ]
    out = aggregate(
        goal="g",
        steps=steps,
        value_gate={"ok": True},
        stopped_reason="planner_final",
        files_accessed=["/a.py"],
    )
    assert "### Steps" in (out.get("investigation_trace") or "")
    assert "### Findings" in (out.get("investigation_trace") or "")


def test_try_reuse_retrieval_match(tmp_path):
    from autonomous.reuse_retrieval import try_reuse_retrieval
    from layla.tools.sandbox_core import set_effective_sandbox

    set_effective_sandbox(str(tmp_path))
    try:
        goal = "Investigate authentication modules across the codebase for regression risks."
        layla = tmp_path / ".layla"
        layla.mkdir()
        rec = {
            "goal": goal,
            "summary": "authentication modules regression analysis",
            "findings": [{"insight": "check auth", "evidence": ["a.py:1"]}],
            "confidence": "high",
            "run_id": "rid1",
        }
        (layla / "investigation_reuse.jsonl").write_text(json.dumps(rec) + "\n", encoding="utf-8")
        hit = try_reuse_retrieval(
            goal=goal,
            workspace_root=str(tmp_path),
            cfg={"autonomous_reuse_match_threshold": 0.05},
        )
        assert hit and hit["matched_run_id"] == "rid1"
    finally:
        set_effective_sandbox(None)


def test_try_wiki_retrieval_match(tmp_path):
    from autonomous.wiki_retrieval import try_wiki_retrieval
    from layla.tools.sandbox_core import set_effective_sandbox

    set_effective_sandbox(str(tmp_path))
    try:
        wr = tmp_path / ".layla" / "wiki"
        wr.mkdir(parents=True)
        goal = "Analyze repository structure packages entry points configuration"
        (wr / "layout.md").write_text(
            "# Repository structure\n\nPackages entry points and configuration.\n",
            encoding="utf-8",
        )
        hit = try_wiki_retrieval(
            goal=goal,
            workspace_root=str(tmp_path),
            cfg={"autonomous_wiki_match_threshold": 0.05},
        )
        assert hit and hit.get("wiki_slug") == "layout"
    finally:
        set_effective_sandbox(None)


def test_prefetch_reuse_skips_planner(monkeypatch, tmp_path):
    from autonomous.controller import run_autonomous_task
    from autonomous.types import AutonomousTask
    from layla.tools.sandbox_core import set_effective_sandbox

    class BoomPlanner:
        def __init__(self, *a, **k):
            raise AssertionError("planner constructed")

    monkeypatch.setattr("autonomous.controller.Planner", BoomPlanner)
    set_effective_sandbox(str(tmp_path))
    try:
        goal = "Trace dependency injection patterns across services for audit purposes."
        layla = tmp_path / ".layla"
        layla.mkdir()
        rec = {
            "goal": goal,
            "summary": "dependency injection patterns across services",
            "findings": [{"insight": "DI", "evidence": []}],
            "confidence": "high",
            "run_id": "x",
        }
        (layla / "investigation_reuse.jsonl").write_text(json.dumps(rec) + "\n", encoding="utf-8")
        task = AutonomousTask(
            goal=goal,
            workspace_root=str(tmp_path),
            max_steps=5,
            timeout_seconds=60,
            confirm_autonomous=True,
        )
        out = run_autonomous_task(
            task=task,
            cfg={"autonomous_reuse_match_threshold": 0.08, "autonomous_prefetch_enabled": True},
        )
        assert out.get("source") == "reuse"
        assert out.get("reused") is True
        assert out.get("stopped_reason") == "reuse_hit"
        assert out.get("steps_used") == 0
    finally:
        set_effective_sandbox(None)


def test_maybe_wiki_export_respects_gates(monkeypatch, tmp_path):
    from autonomous.controller import _maybe_export_wiki_markdown
    from autonomous.types import AutonomousTask

    captured: dict[str, Any] = {}

    def fake_write(**kwargs):
        captured.update(kwargs)
        return {"ok": True, "path": str(tmp_path / "out.md")}

    monkeypatch.setattr("autonomous.controller.write_wiki_entry", fake_write)
    task = AutonomousTask(
        goal="Investigate modules across files for audit.",
        workspace_root=str(tmp_path),
        allow_write=True,
        confirm_autonomous=True,
    )
    final = {"confidence": "high", "summary": "S", "findings": [{"insight": "i", "evidence": []}]}
    r = _maybe_export_wiki_markdown(
        task=task,
        cfg={"autonomous_wiki_enabled": True, "autonomous_wiki_export_enabled": True},
        final=final,
        unique_files=2,
    )
    assert r and r.get("ok")
    assert captured.get("allow_write") is True


def test_planner_rejects_bad_tool_gracefully(monkeypatch):
    from autonomous.planner import Planner

    calls = {"n": 0}

    def fake_completion(prompt, **kwargs):
        calls["n"] += 1
        if calls["n"] == 1:
            return {"choices": [{"message": {"content": '{"type":"tool","tool":"shell","args":{}}'}}]}
        return {"choices": [{"message": {"content": '{"type":"final","final":{"summary":"ok"}}'}}]}

    monkeypatch.setattr("autonomous.planner.run_completion", fake_completion)
    p = Planner(tool_allowlist=["read_file"])
    d = p.decide(goal="x", context={}, budget_hint="b")
    assert d.type == "final"

