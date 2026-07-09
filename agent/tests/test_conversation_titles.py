"""Phase 3a: conversation rail titles are TOPIC names, not a raw 40-char slice of message #1.

Operator complaint: chats named with "timestamp bs" / a truncated first line. Now the instant
title is an extractive topic phrase (filler stripped), optionally polished async by an LLM.
"""
import sys
from pathlib import Path

AGENT_DIR = Path(__file__).resolve().parent.parent
if str(AGENT_DIR) not in sys.path:
    sys.path.insert(0, str(AGENT_DIR))


def test_extractive_title_strips_filler_and_framing():
    from layla.memory.conversations import _auto_name_conversation as an
    assert an("can you help me refactor the auth module please") == "Refactor the auth module"
    assert "CI pipeline" in an("How do I set up a CI pipeline for this repo?")
    assert an("hey so I want to build a CNC toolpath generator") == "Build a CNC toolpath generator"
    assert an("fix the bug in login") == "Fix the bug in login"


def test_no_ellipsis_truncation_and_empty():
    from layla.memory.conversations import _auto_name_conversation as an
    long = an("please explain in great detail how the entire distributed inference subsystem works end to end")
    assert "..." not in long and len(long) <= 55
    assert an("") == "New chat"
    assert an("   \n  ") == "New chat"


def test_llm_title_cleaner_rejects_scaffolding():
    from services.agent.title_synthesizer import _clean_title
    assert _clean_title('Title: "Auth Refactor"') == "Auth Refactor"
    assert _clean_title("[MORRIGAN] CI Setup Guide.") == "CI Setup Guide"
    assert _clean_title("As an AI, I cannot") == ""
    assert _clean_title("   ") == ""
    assert _clean_title("...") == ""


def test_synthesizer_needs_some_content():
    from services.agent.title_synthesizer import synthesize_conversation_title
    assert synthesize_conversation_title("", "") == ""


def test_title_synthesis_flag_default_on():
    import runtime_safety
    assert runtime_safety.load_config().get("conversation_title_synthesis_enabled") is True
