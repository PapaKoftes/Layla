"""
Tests for the decision-time tool list injected into the decision prompt.
"""
import re
import sys
from pathlib import Path

AGENT_DIR = Path(__file__).resolve().parent.parent
if str(AGENT_DIR) not in sys.path:
    sys.path.insert(0, str(AGENT_DIR))


def test_tool_names_for_decision_includes_reason():
    from services.prompts.prompt_builder import tool_names_for_decision

    s = tool_names_for_decision({"reason", "read_file", "grep_code"}, "read file agent/main.py")
    # reason still leads the list (now with a gloss).
    assert s.split(",")[0].strip().startswith("reason")
    assert "read_file" in s


def test_shortlisted_tools_carry_use_when_glosses():
    """ts03: bare tool names force a 3B to disambiguate read_file vs grep_code from token
    familiarity — the measured read_file monoculture. Each offered tool now carries a terse
    parenthetical 'use when' gloss so the model can pick by MEANING.

    Teeth: revert tool_names_for_decision to `", ".join(["reason", *names])` and this fails at
    the `read_file (` / distinct-gloss assertions.
    """
    from services.prompts.prompt_builder import tool_names_for_decision

    s = tool_names_for_decision(
        {"reason", "read_file", "grep_code", "list_dir"}, "find the symbol foo"
    )
    assert "read_file (" in s and "grep_code (" in s and "list_dir (" in s
    glosses = dict(re.findall(r"(\w+) \(([^)]+)\)", s))
    # The glosses must actually differ so they disambiguate (not a constant label).
    assert glosses.get("read_file") and glosses.get("grep_code")
    assert glosses["read_file"] != glosses["grep_code"]
    # No comma inside a gloss — keeps the comma-joined offered list unambiguous.
    for g in glosses.values():
        assert "," not in g


def test_gloss_is_empty_string_for_unknown_tool():
    """A name with no registered description emits the bare name (no empty parens)."""
    from services.prompts.prompt_builder import _decision_tool_gloss, tool_names_for_decision

    assert _decision_tool_gloss("this_tool_does_not_exist_zzz") == ""
    s = tool_names_for_decision({"reason", "this_tool_does_not_exist_zzz"}, "hi")
    assert "this_tool_does_not_exist_zzz" in s
    assert "()" not in s  # never an empty gloss
