from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
AGENT = Path(__file__).resolve().parent.parent
if str(AGENT) not in sys.path:
    sys.path.insert(0, str(AGENT))


def test_validate_plan_before_execution_injects_inspect_step() -> None:
    from services.planner import validate_plan_before_execution

    plan = [{"step": 1, "task": "Edit file", "tools": ["write_file"]}]
    out, ok, _reason = validate_plan_before_execution(plan, cfg={"max_plan_steps": 6}, workspace_root="C:/x")
    assert ok is True
    assert out[0]["task"].lower().startswith("inspect")


def test_validate_plan_before_execution_caps_and_renumbers() -> None:
    from services.planner import validate_plan_before_execution

    plan = [{"step": i + 1, "task": f"t{i}", "tools": []} for i in range(10)]
    out, ok, _reason = validate_plan_before_execution(plan, cfg={"max_plan_steps": 3}, workspace_root="")
    assert ok is True
    assert len(out) == 3
    assert [s["step"] for s in out] == [1, 2, 3]
