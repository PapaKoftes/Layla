"""An explicit "create file X" request with writes allowed is offered write_file whatever the last turn scored.

Live (jinx-20b, 3 identical rounds): round 2's "Create a file named write_probe_1.txt ... banana" got steps
['reason'] and wrote nothing. The decision took the same ~6s as the rounds that wrote, so it was not a decode
failure: write_file was simply not offered. A previous turn scoring < 0.45 forbids every mutating tool on the
conversation's next turn, and that heuristic (meant to restrain the model's own initiative) vetoed the
operator's explicit instruction. Writes still go through the approval gate.
"""
import sys
import uuid
from pathlib import Path

AGENT_DIR = Path(__file__).resolve().parent.parent
if str(AGENT_DIR) not in sys.path:
    sys.path.insert(0, str(AGENT_DIR))

WRITE_MSG = "Create a file named notes_a.txt in the workspace containing exactly the word banana."
ALL = frozenset({"read_file", "list_dir", "write_file", "apply_patch", "shell", "reason"})


def _offered(state, low_prev: bool):
    from services.infrastructure.session_context import get_or_create_session
    from services.safety.decision_policy import apply_caps_to_valid_tools, build_policy_caps

    cid = "t-" + uuid.uuid4().hex
    if low_prev:
        get_or_create_session(cid).set_outcome_evaluation({"score": 0.35, "success": False})
    caps = build_policy_caps(state, {"decision_policy_enabled": True}, conversation_id=cid)
    return apply_caps_to_valid_tools(ALL, caps)


def test_probe_low_previous_score_really_forbids_writes_on_an_ordinary_turn():
    # Precondition: the veto this file is about exists — otherwise the next test proves nothing.
    tools = _offered({"original_goal": "Fix the bug in parser.py", "allow_write": True, "steps": []}, low_prev=True)
    assert "write_file" not in tools, "PROBE BROKEN: a 0.35 previous score no longer forbids mutating tools"


def test_explicit_write_request_is_still_offered_write_file():
    tools = _offered({"original_goal": WRITE_MSG, "_allow_write": True, "steps": []}, low_prev=True)
    assert "write_file" in tools


def test_without_write_permission_the_previous_turn_still_restrains():
    tools = _offered({"original_goal": WRITE_MSG, "steps": []}, low_prev=True)
    assert "write_file" not in tools


def test_a_question_about_writing_is_not_an_explicit_request():
    tools = _offered({"original_goal": "How do I create a file named a.txt in Python?", "allow_write": True,
                      "steps": []}, low_prev=True)
    assert "write_file" not in tools


def test_automatic_pre_read_probe_is_not_work_done_for_the_verify_gate():
    import services.safety.decision_policy as dp

    state = {"original_goal": "Fix the bug in parser.py", "allow_write": True,
             "steps": [{"action": "pre_read_probe", "path": "parser.py", "result": {"ok": True}}],
             "cognitive_workspace": {"strategy_hint": "read first, then edit"}}
    caps = dp.build_policy_caps(state, {"decision_policy_enabled": True}, conversation_id="t-" + uuid.uuid4().hex)
    assert caps.require_verify_before_mutate, "PROBE BROKEN: strategy hint no longer requires verify"
    assert "write_file" not in caps.forbidden_tools, caps.to_trace_dict()

    state["steps"].append({"action": "web_search", "result": {"ok": True}})  # real work, no verify: gate applies
    caps = dp.build_policy_caps(state, {"decision_policy_enabled": True}, conversation_id="t-" + uuid.uuid4().hex)
    assert "write_file" in caps.forbidden_tools
