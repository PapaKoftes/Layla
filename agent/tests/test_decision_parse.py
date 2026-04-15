from __future__ import annotations


def test_parse_decision_handles_markdown_fence_and_multiline():
    from decision_schema import parse_decision

    text = """Here you go:
```json
{
  "action": "tool",
  "tool": "read_file",
  "priority_level": "high",
  "args": {"path": "agent/main.py"}
}
```
extra trailing text
"""
    d = parse_decision(text, frozenset({"read_file"}))
    assert d is not None
    assert d["action"] == "tool"
    assert d["tool"] == "read_file"
    assert d["args"]["path"] == "agent/main.py"


def test_parse_decision_repairs_trailing_commas():
    from decision_schema import parse_decision

    text = '{"action":"reason","objective_complete":true,}'
    d = parse_decision(text, frozenset({"read_file"}))
    assert d is not None
    assert d["action"] == "reason"
    assert d["objective_complete"] is True

