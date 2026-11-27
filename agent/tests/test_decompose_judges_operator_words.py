"""Goal decomposition judges the operator's message, not the enrichment prefix.

"[Active workspace: <path>]" + newline + "Say hello in one short sentence." is over 80 chars only because of the
prefix; it was classed "broad", costing an extra ~4 s model call per turn and injecting LLM sub-objectives as
the turn's TASK.
"""
import sys
from pathlib import Path

AGENT_DIR = Path(__file__).resolve().parent.parent
if str(AGENT_DIR) not in sys.path:
    sys.path.insert(0, str(AGENT_DIR))


def test_short_message_behind_a_workspace_prefix_is_not_decomposed(monkeypatch):
    from services.prompts import system_head_builder as shb

    calls = []
    monkeypatch.setattr(shb, "run_completion", lambda *a, **k: calls.append(a) or {"choices": [{"text": '["a", "b"]'}]})
    goal = r"[Active workspace: C:\Users\someone\layla-workspace]" + "\nSay hello in one short sentence."
    assert len(goal) > 80, "PROBE BROKEN: the prefixed goal must exceed the broadness length"
    assert shb.decompose_goal(goal) == []
    assert calls == []


def test_a_genuinely_broad_request_still_decomposes(monkeypatch):
    from services.prompts import system_head_builder as shb

    monkeypatch.setattr(shb, "run_completion", lambda *a, **k: {"choices": [{"text": '["Add tests", "Fix lint"]'}]})
    goal = r"[Active workspace: C:\ws]" + "\nRefactor the retry logic and make this repo production ready."
    assert shb.decompose_goal(goal) == ["Add tests", "Fix lint"]
