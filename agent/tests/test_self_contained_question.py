"""Golden-eval fix: self-contained questions get a direct answer, not a tool detour."""
from __future__ import annotations

from services.agent import response_builder as rb


def test_general_knowledge_is_self_contained():
    for q in [
        "What is the capital of France?",
        "What is 2 + 2?",
        "Reverse the string 'hello'",
        "Correct this German sentence: Ich habe gegessen ein Apfel",
        "Convert 5 km to miles",
        "If all A are B and all B are C, are all A C?",
        "Write a haiku about autumn",
        "Count the items: apple, pear, plum",
    ]:
        assert rb.is_self_contained_question(q), q


def test_tool_needing_questions_are_not():
    for q in [
        "Read the file config.json and tell me the port",
        "What did we discuss last time about auth?",
        "Search for the latest news on AI",
        "Run the tests and show failures",
        "What's my name?",
        "Summarize this repo's architecture",
        "Install numpy and import it",
        "What's in my todo list?",
        r"Write path C:\Users\me\golden_e2e.txt with content golden_line_content",
        "Write path /home/me/notes.txt with content hello",
        "Read config.json and tell me the port",
        "Edit ./src/main.py to add logging",
    ]:
        assert not rb.is_self_contained_question(q), q


def test_casual_slashes_stay_self_contained():
    # narrow path regex must not trip on everyday slashes/units
    for q in ["What is 60 km/h in mph?", "Is it and/or in logic?", "Define n/a"]:
        assert rb.is_self_contained_question(q), q


def test_empty_or_huge_is_not_self_contained():
    assert not rb.is_self_contained_question("")
    assert not rb.is_self_contained_question("x")
    assert not rb.is_self_contained_question("a" * 2500)


def test_reexported_from_agent_loop():
    import agent_loop
    assert agent_loop._is_self_contained_question("What is the capital of France?")
    assert not agent_loop._is_self_contained_question("read the file x.py")
