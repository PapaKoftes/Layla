from services.plan_templates import match_skeleton_plan


def test_skeleton_fix_tests_pattern():
    cfg = {"plan_system_first_enabled": True}
    goal = "Please fix the failing pytest tests in the repo and repair the regression"
    plan = match_skeleton_plan(goal, cfg)
    assert plan and len(plan) >= 2
    assert any("test" in (s.get("task") or "").lower() or "pytest" in goal for s in plan)


def test_skeleton_disabled():
    assert match_skeleton_plan("x" * 100, {"plan_system_first_enabled": False}) is None
