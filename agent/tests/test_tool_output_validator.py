"""Tests for services/tool_output_validator.py."""
from __future__ import annotations

from services.tool_output_validator import validate_tool_output


def test_non_dict_wrapped() -> None:
    r = validate_tool_output("any_tool", "not-a-dict")
    assert r["ok"] is False
    assert r.get("error") == "tool_output_invalid"


def test_ok_false_gets_error_when_missing() -> None:
    r = validate_tool_output("t", {"ok": False})
    assert r.get("error") == "tool_returned_no_ok"


def test_ok_false_keeps_reason_without_duplicate_error() -> None:
    r = validate_tool_output("t", {"ok": False, "reason": "approval_required"})
    assert r.get("error") != "tool_returned_no_ok"
    assert r.get("reason") == "approval_required"


def test_ok_true_empty_flagged() -> None:
    r = validate_tool_output("t", {"ok": True})
    assert r.get("_empty_output") is True


def test_ok_true_with_stdout_not_empty() -> None:
    r = validate_tool_output("t", {"ok": True, "stdout": "hello"})
    assert not r.get("_empty_output")
