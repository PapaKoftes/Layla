"""Tests for _apply_lite_mode_overrides in agent_loop.py."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def _get_fn():
    from agent_loop import _apply_lite_mode_overrides
    return _apply_lite_mode_overrides


def test_low_mode_limits_tool_calls():
    fn = _get_fn()
    cfg = {"performance_mode": "low", "max_tool_calls": 10}
    out = fn(cfg)
    assert out["max_tool_calls"] == 2


def test_low_mode_disables_workspace():
    fn = _get_fn()
    cfg = {"performance_mode": "low", "enable_cognitive_workspace": True}
    out = fn(cfg)
    assert out["enable_cognitive_workspace"] is False


def test_low_mode_disables_planning():
    fn = _get_fn()
    cfg = {"performance_mode": "low", "planning_enabled": True}
    out = fn(cfg)
    assert out["planning_enabled"] is False


def test_low_mode_sets_retrieval_k():
    fn = _get_fn()
    cfg = {"performance_mode": "low"}
    out = fn(cfg)
    assert out["retrieval_k"] == 3


def test_low_mode_skip_flags():
    fn = _get_fn()
    cfg = {"performance_mode": "low"}
    out = fn(cfg)
    assert out["skip_deliberation"] is True
    assert out["skip_self_reflection"] is True


def test_mid_mode_limits_tool_calls():
    fn = _get_fn()
    cfg = {"performance_mode": "mid", "max_tool_calls": 10}
    out = fn(cfg)
    assert out["max_tool_calls"] == 4


def test_mid_mode_disables_workspace():
    fn = _get_fn()
    cfg = {"performance_mode": "mid", "enable_cognitive_workspace": True}
    out = fn(cfg)
    assert out["enable_cognitive_workspace"] is False


def test_mid_mode_keeps_planning():
    fn = _get_fn()
    cfg = {"performance_mode": "mid", "planning_enabled": True}
    out = fn(cfg)
    assert out["planning_enabled"] is True


def test_high_mode_does_not_limit():
    fn = _get_fn()
    cfg = {"performance_mode": "high", "max_tool_calls": 10, "enable_cognitive_workspace": True}
    out = fn(cfg)
    assert out["max_tool_calls"] == 10
    assert out["enable_cognitive_workspace"] is True


def test_auto_mode_does_not_limit():
    fn = _get_fn()
    cfg = {"performance_mode": "auto", "max_tool_calls": 8}
    out = fn(cfg)
    assert out["max_tool_calls"] == 8


def test_does_not_mutate_input():
    fn = _get_fn()
    cfg = {"performance_mode": "low", "max_tool_calls": 10}
    fn(cfg)
    assert cfg["max_tool_calls"] == 10  # original unchanged
