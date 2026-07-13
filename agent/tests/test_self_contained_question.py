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


def test_installed_adjective_is_self_contained_but_imperative_install_is_not():
    # "install" (bare substring) matched "installed", so "list your capabilities, especially the
    # installed ones" was routed into the tool loop and burned the tool budget without answering.
    # A question ABOUT what's installed is answerable directly; an imperative install still needs tools.
    for q in [
        "can you list in a table everything that you are capable of doing, especially the installed ones?",
        "what features are installed",
        "which capabilities do i have installed",
    ]:
        assert rb.is_self_contained_question(q), q
    for q in ["install numpy for me", "pip install requests", "npm install react"]:
        assert not rb.is_self_contained_question(q), q


def test_reexported_from_agent_loop():
    import agent_loop
    assert agent_loop._is_self_contained_question("What is the capital of France?")
    assert not agent_loop._is_self_contained_question("read the file x.py")


def test_possessive_personal_data_imperatives_need_tools():
    # audit #4 (HIGH): a possessive reference to stored personal data is NOT self-contained even without
    # a '?', so tools/memory aren't suppressed and the model doesn't hallucinate an answer.
    from services.agent.response_builder import is_self_contained_question as Q
    for g in ("summarize my meeting notes", "summarize my emails", "check my calendar",
              "list my meeting notes", "delete my draft", "what are my tasks?",
              "what's in my todo list?"):
        assert Q(g) is False, g
    # …but a genuinely self-contained possessive (no personal-data referent) stays self-contained.
    for g in ("write a poem about my dog", "my favorite color is blue, suggest a matching shade"):
        assert Q(g) is True, g
