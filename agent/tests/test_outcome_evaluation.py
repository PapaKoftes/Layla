from services.outcome_evaluation import evaluate_outcome


def test_evaluate_outcome_all_ok():
    state = {
        "status": "finished",
        "steps": [
            {"action": "read_file", "result": {"ok": True, "path": "a.py"}},
            {"action": "reason", "result": "done"},
        ],
    }
    out = evaluate_outcome(state)
    assert out["success"] is True
    assert out["tool_fail"] == 0
    assert out["score"] > 0.5


def test_evaluate_outcome_with_failures():
    state = {
        "status": "finished",
        "steps": [
            {"action": "shell", "result": {"ok": False, "error": "nope"}},
        ],
    }
    out = evaluate_outcome(state)
    assert out["tool_fail"] >= 1
    assert out["issues"]
    assert out["success"] is False
    assert out["score"] < 0.85
