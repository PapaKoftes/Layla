"""Tests for optional structured decision normalization (no outlines required)."""

from __future__ import annotations

from services.structured_gen import _normalize_outlines_result


def test_normalize_outlines_result_basic():
    vt = frozenset({"read_file", "list_dir"})
    d = _normalize_outlines_result(
        {
            "action": "tool",
            "tool": "read_file",
            "args": {"path": "a.py"},
            "batch_tools": [],
            "priority_level": "high",
        },
        vt,
    )
    assert d is not None
    assert d["action"] == "tool"
    assert d["tool"] == "read_file"
    assert d["args"] == {"path": "a.py"}


def test_normalize_invalid_tool_dropped():
    vt = frozenset({"read_file"})
    d = _normalize_outlines_result({"action": "tool", "tool": "rm_rf", "args": {}}, vt)
    assert d is not None
    assert d["tool"] is None


def test_normalize_pydantic_like():
    class Fake:
        def model_dump(self):
            return {"action": "reason", "objective_complete": True, "priority_level": "low"}

    vt = frozenset({"read_file"})
    d = _normalize_outlines_result(Fake(), vt)
    assert d is not None
    assert d["action"] == "reason"
    assert d["objective_complete"] is True
