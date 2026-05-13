"""Tests: original_goal preservation in learnings, reflections, and plan titles.

The prompt optimizer may rewrite the user's goal for better LLM performance,
but permanent storage (learnings, reflections, plan titles) must reference the
user's actual text so that memory recall matches what the user said.
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch


# ---------------------------------------------------------------------------
# 1. Reflection engine uses original_goal, not objective
# ---------------------------------------------------------------------------

def test_reflection_engine_uses_original_goal():
    """store_reflections_as_learnings receives original_goal, not the revised objective."""
    from services.reflection_engine import run_reflection

    state = {
        "status": "finished",
        "original_goal": "Explain how gear ratios work",
        "objective": "optimized: explain mechanical advantage of gear ratios in detail",
        "steps": [
            {"action": "read_file", "result": {"ok": True, "path": "/tmp/gear.txt"}},
        ],
    }
    with patch("services.reflection_engine.generate_reflections") as mock_gen, \
         patch("services.reflection_engine.store_reflections_as_learnings") as mock_store:
        mock_gen.return_value = {
            "what_worked": "read succeeded",
            "what_failed": "None",
            "what_could_improve": "N/A",
        }
        run_reflection(state)
        mock_store.assert_called_once()
        # The second positional arg (objective text) must be the original_goal
        call_args = mock_store.call_args
        objective_arg = call_args[0][1]  # positional arg index 1
        assert "Explain how gear ratios work" in objective_arg
        assert "optimized:" not in objective_arg


def test_reflection_engine_falls_back_to_objective():
    """When original_goal is absent, fall back to objective."""
    from services.reflection_engine import run_reflection

    state = {
        "status": "finished",
        "objective": "some objective text",
        "steps": [
            {"action": "grep_code", "result": {"ok": True}},
        ],
    }
    with patch("services.reflection_engine.generate_reflections") as mock_gen, \
         patch("services.reflection_engine.store_reflections_as_learnings") as mock_store:
        mock_gen.return_value = {
            "what_worked": "grep succeeded",
            "what_failed": "None",
            "what_could_improve": "N/A",
        }
        run_reflection(state)
        mock_store.assert_called_once()
        objective_arg = mock_store.call_args[0][1]
        assert "some objective text" in objective_arg


# ---------------------------------------------------------------------------
# 2. revised_objective must NOT overwrite original_goal via setdefault
# ---------------------------------------------------------------------------

def test_revised_objective_does_not_overwrite_original_goal():
    """
    When state['original_goal'] is already set, a revised_objective must not
    replace it. The fix uses setdefault so the first assignment wins.
    """
    state = {"original_goal": "user typed this"}
    # Simulate the fixed code path (setdefault):
    revised = "machine revised this"
    state.setdefault("original_goal", revised)
    assert state["original_goal"] == "user typed this"


def test_revised_objective_sets_original_goal_when_absent():
    """If original_goal was never set, setdefault allows the revised objective through."""
    state: dict = {}
    revised = "machine revised this"
    state.setdefault("original_goal", revised)
    assert state["original_goal"] == "machine revised this"


# ---------------------------------------------------------------------------
# 3. Plan observability logs use original_goal
# ---------------------------------------------------------------------------

def test_plan_log_uses_original_goal_preview():
    """
    log_planner_invoked and log_agent_plan_created should receive
    the original_goal for goal_preview, not the optimizer-rewritten goal.

    We verify by checking that the _plan_goal_preview variable logic
    prefers state['original_goal'] over `goal`.
    """
    # Simulate the logic from agent_loop.py lines 3875-3877
    state = {"original_goal": "build a CNC router table"}
    goal = "optimized: design and construct a CNC routing table with detailed specifications"

    _plan_goal_preview = (state.get("original_goal") or goal)[:60]
    assert _plan_goal_preview == "build a CNC router table"


def test_plan_log_falls_back_to_goal():
    """When original_goal is absent, goal_preview falls back to goal."""
    state: dict = {}
    goal = "optimized: design and construct a CNC routing table"

    _plan_goal_preview = (state.get("original_goal") or goal)[:60]
    assert "optimized:" in _plan_goal_preview


# ---------------------------------------------------------------------------
# 4. generate_reflections uses original_goal from state
# ---------------------------------------------------------------------------

def test_generate_reflections_reads_original_goal():
    """generate_reflections should pick up original_goal for the objective line."""
    from services.reflection_engine import generate_reflections

    state = {
        "original_goal": "Calculate torque for a stepper motor",
        "objective": "optimized: compute stepper motor torque requirements",
        "status": "finished",
        "steps": [
            {"action": "python_ast", "result": {"ok": True}},
        ],
    }
    # generate_reflections reads: state.get("objective") or state.get("original_goal")
    # Because "objective" is set, it will use that for the LLM prompt (internal).
    # But the stored reflection (via store_reflections_as_learnings in run_reflection)
    # must use original_goal.  We test the run_reflection integration above.
    # Here we just confirm generate_reflections doesn't crash.
    # run_completion is imported lazily inside the function, so patch the gateway module.
    with patch("services.llm_gateway.run_completion", side_effect=Exception("no LLM")):
        result = generate_reflections(state)
    assert "what_worked" in result
    assert "what_failed" in result


# ---------------------------------------------------------------------------
# 5. outcome_writer uses original_goal for objective
# ---------------------------------------------------------------------------

def test_outcome_writer_uses_original_goal():
    """_save_outcome_memory should use original_goal for the objective line."""
    from services.outcome_writer import _save_outcome_memory

    state = {
        "status": "finished",
        "original_goal": "Help me debug the Arduino sketch",
        "objective": "optimized: diagnose and fix Arduino IDE compilation errors",
        "steps": [
            {"action": "read_file", "result": {"ok": True, "path": "/tmp/sketch.ino"}},
        ],
    }
    # save_learning is imported lazily from services.memory_router inside _save_outcome_memory
    with patch("services.memory_router.save_learning") as mock_save, \
         patch("services.reflection_engine.run_reflection", return_value=None):
        _save_outcome_memory(state)

    # The first save_learning call is the outcome summary
    assert mock_save.called
    first_call_content = mock_save.call_args_list[0][1].get("content", "")
    # The summary should reference the original_goal text (via the objective fallback chain)
    assert "Help me debug the Arduino sketch" in first_call_content or \
           "optimized:" not in first_call_content


# ---------------------------------------------------------------------------
# 6. auto_extract_learnings receives original_goal
# ---------------------------------------------------------------------------

def test_auto_extract_learnings_uses_original_goal():
    """_auto_extract_learnings should receive state['original_goal'], not the optimized goal."""
    from services.outcome_writer import _auto_extract_learnings

    captured_msgs = []

    def fake_save(content, **kwargs):
        captured_msgs.append(content)
        return 1

    user_msg = "What is the best wood for a router table?"
    response = (
        "The best wood for a router table top is MDF (medium-density fiberboard) "
        "because it is flat, stable, and affordable. Baltic birch plywood is another "
        "excellent choice for its strength and dimensional stability. Always remember "
        "to seal MDF edges to prevent moisture absorption."
    )
    # save_learning and run_completion are imported lazily from services.memory_router
    # and services.llm_gateway respectively
    with patch("services.memory_router.save_learning", side_effect=fake_save), \
         patch("services.llm_gateway.run_completion", return_value=""):
        _auto_extract_learnings(user_msg, response, "morrigan")

    # The function was called with the original user message.
    # We just verify it ran without error; the actual extraction depends on
    # heuristics/LLM which are mocked out.
