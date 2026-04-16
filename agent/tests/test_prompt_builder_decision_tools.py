"""
Tests for the decision-time tool list injected into the decision prompt.
"""
import sys
from pathlib import Path

AGENT_DIR = Path(__file__).resolve().parent.parent
if str(AGENT_DIR) not in sys.path:
    sys.path.insert(0, str(AGENT_DIR))


def test_tool_names_for_decision_includes_reason():
    from services.prompt_builder import tool_names_for_decision

    s = tool_names_for_decision({"reason", "read_file", "grep_code"}, "read file agent/main.py")
    assert s.split(",")[0].strip() == "reason"
    assert "read_file" in s
