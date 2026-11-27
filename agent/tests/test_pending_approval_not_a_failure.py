"""A tool call waiting for operator approval is not a failure.

Scored as one, a correct approval-gated write turn fell below 0.45, and caps_from_outcome_evaluation then
forbade every mutating tool on the conversation's next turn — live, the second "create a file" request was
never offered write_file and the reply claimed "File created." anyway.
"""
import sys
from pathlib import Path

AGENT_DIR = Path(__file__).resolve().parent.parent
if str(AGENT_DIR) not in sys.path:
    sys.path.insert(0, str(AGENT_DIR))

PENDING_WRITE = {"status": "finished", "steps": [
    {"action": "write_file", "args": {"path": "a.txt"},
     "result": {"ok": False, "reason": "approval_required", "approval_id": "x"}},
]}


def test_pending_approval_does_not_lower_the_score_or_forbid_writes():
    from services.infrastructure.outcome_evaluation import evaluate_outcome
    from services.safety.decision_policy import _MUTATING_TOOLS, caps_from_outcome_evaluation

    ev = evaluate_outcome(PENDING_WRITE)
    assert ev["tool_fail"] == 0 and ev["success"], ev
    caps = caps_from_outcome_evaluation(ev)
    assert not (caps.forbidden_tools & _MUTATING_TOOLS), caps.to_trace_dict()


def test_a_real_failure_still_counts():
    from services.infrastructure.outcome_evaluation import evaluate_outcome

    failed = {"status": "finished", "steps": [{"action": "write_file", "result": {"ok": False, "error": "disk full"}}]}
    assert evaluate_outcome(failed)["tool_fail"] == 1


def test_matrix_uses_the_same_rule():
    from services.infrastructure.outcome_evaluation import evaluate_validation_matrix

    m = evaluate_validation_matrix(PENDING_WRITE)
    assert "tool_fail" not in " ".join(sum((v for v in m.get("reasons", {}).values()), [])) if isinstance(m.get("reasons"), dict) else True
