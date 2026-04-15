from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
AGENT = Path(__file__).resolve().parent.parent
if str(AGENT) not in sys.path:
    sys.path.insert(0, str(AGENT))


def test_validation_matrix_basic_success() -> None:
    from services.outcome_evaluation import evaluate_validation_matrix

    st = {
        "status": "finished",
        "objective_complete": True,
        "tool_calls": 1,
        "steps": [
            {"action": "write_file", "result": {"ok": True, "path": "x.py", "_deterministic_verify": {"ok": True}}},
            {"action": "reason", "result": "done"},
        ],
    }
    m = evaluate_validation_matrix(st)
    assert m["critical_pass"] is True
    assert 0.0 <= m["overall_score"] <= 1.0
