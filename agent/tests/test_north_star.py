"""
Tests for North Star–aligned features: project context (lifecycle), file understanding.
Run: cd agent && python -m pytest tests/test_north_star.py -v
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def test_project_context_lifecycle():
    """Project context supports lifecycle_stage (North Star §3)."""
    from layla.memory.db import migrate, get_project_context, set_project_context, PROJECT_LIFECYCLE_STAGES

    migrate()
    assert PROJECT_LIFECYCLE_STAGES == ("idea", "planning", "prototype", "iteration", "execution", "reflection")

    set_project_context(project_name="TestProject", lifecycle_stage="planning")
    pc = get_project_context()
    assert pc["project_name"] == "TestProject"
    assert pc["lifecycle_stage"] == "planning"

    set_project_context(lifecycle_stage="EXECUTION")
    pc = get_project_context()
    assert pc["lifecycle_stage"] == "execution"

    set_project_context(lifecycle_stage="invalid")
    pc = get_project_context()
    assert pc["lifecycle_stage"] == "execution"


def test_file_understanding_extensions():
    """File understanding supports North Star §4 extensions."""
    from layla.file_understanding import get_supported_extensions, analyze_file

    exts = get_supported_extensions()
    for e in (".3dm", ".gh", ".dxf", ".py", ".md", ".json", ".ipynb", ".nc", ".gcode", ".stl", ".svg"):
        assert e in exts, f"missing {e}"

    from pathlib import Path
    tmp = Path(__file__).parent / "sample_north_star.md"
    tmp.write_text("# Hello\n## World", encoding="utf-8")
    try:
        out = analyze_file(tmp)
        assert out.get("format") == "Markdown"
        assert "intent" in out
    finally:
        tmp.unlink(missing_ok=True)


def test_file_understanding_intent_by_ext():
    """Intent returned for binary/opaque formats without content."""
    from layla.file_understanding import analyze_file

    out = analyze_file(file_path="dummy.stl", content=None)
    assert out["format"] == "STL"
    assert "intent" in out and "mesh" in out["intent"].lower()

    out = analyze_file(file_path="dummy.gcode", content=None)
    assert out["format"] == "G-code"
    assert "machine" in out["intent"].lower() or "cnc" in out["intent"].lower()


def test_wakeup_initiative_suggestion():
    """North Star §10+§14: _wakeup_initiative_suggestion returns a short suggestion based on project/plans."""
    from routers.study import _wakeup_initiative_suggestion

    # No project -> empty or generic
    out = _wakeup_initiative_suggestion([], [])
    assert isinstance(out, str)

    # With active plans -> suggestion about study
    out = _wakeup_initiative_suggestion([{"topic": "asyncio"}], [])
    assert "study" in out.lower() or "plan" in out.lower() or out == ""


def test_initiative_rule_ordering():
    """Data-driven initiative: first matching rule wins; order is planning_and_goals, idea, has_plans, no_stage."""
    from routers.study import INITIATIVE_RULES, _initiative_condition_matches

    assert len(INITIATIVE_RULES) >= 4
    conditions = [r["condition"] for r in INITIATIVE_RULES]
    assert "planning_and_goals" in conditions
    assert "has_plans" in conditions
    # planning_and_goals should match before has_plans when both could apply (project has goals + plans)
    pc_planning = {"project_name": "X", "lifecycle_stage": "planning", "goals": "Ship it"}
    assert _initiative_condition_matches("planning_and_goals", pc_planning, [{"topic": "y"}]) is True
    assert _initiative_condition_matches("has_plans", pc_planning, [{"topic": "y"}]) is True
    # First rule in list that matches is returned by _wakeup_initiative_suggestion; order implies planning_and_goals wins
    idx_planning = conditions.index("planning_and_goals")
    idx_plans = conditions.index("has_plans")
    assert idx_planning < idx_plans


def test_project_discovery_returns_structure(monkeypatch):
    """North Star §18: run_project_discovery returns dict with opportunities, ideas, feasibility_notes."""
    import services.project_discovery as pd

    from services import llm_gateway
    monkeypatch.setattr(
        llm_gateway,
        "run_completion",
        lambda *a, **k: {"choices": [{"message": {"content": '{"opportunities": ["A"], "ideas": ["B"], "feasibility_notes": ["C"]}'}}]},
    )
    result = pd.run_project_discovery()
    assert "opportunities" in result
    assert "ideas" in result
    assert "feasibility_notes" in result
    assert isinstance(result["opportunities"], list)
    assert isinstance(result["ideas"], list)
    assert isinstance(result["feasibility_notes"], list)


def test_project_discovery_malformed_completion_returns_safe_fallback(monkeypatch):
    """Malformed or invalid JSON from completion returns safe structure (no exception)."""
    import services.project_discovery as pd
    from services import llm_gateway

    monkeypatch.setattr(
        llm_gateway,
        "run_completion",
        lambda *a, **k: {"choices": [{"message": {"content": "not valid json at all"}}]},
    )
    result = pd.run_project_discovery()
    assert result == {"opportunities": [], "ideas": [], "feasibility_notes": []}

    monkeypatch.setattr(
        llm_gateway,
        "run_completion",
        lambda *a, **k: {"choices": [{"message": {"content": '{"opportunities": null, "ideas": []}'}}]},
    )
    result2 = pd.run_project_discovery()
    assert "opportunities" in result2 and "ideas" in result2 and "feasibility_notes" in result2
    assert result2["feasibility_notes"] == []
