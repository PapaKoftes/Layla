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


def test_llm_title_cleaner_handles_role_tags_and_affirmations():
    # Round-9: the reject regex wrapped colon/punctuation alternatives in \b...\b, so "Assistant:",
    # "User:" and "Sure!" never matched and leaked verbatim as the conversation title.
    from services.agent.title_synthesizer import _clean_title
    # A bare role tag echoed from the prompt frame is stripped, leaving the clean topic.
    assert _clean_title("Assistant: Python Async Basics") == "Python Async Basics"
    assert _clean_title("User: hello there") == "Hello there"
    # Affirmation openers are rejected (fall back to the extractive title).
    assert _clean_title("Sure! Async/Await Explained") == ""
    assert _clean_title("Sure, Python Tips") == ""
    assert _clean_title("Okay here is a title") == ""
    # A legitimate topic that merely contains a keyword is kept.
    assert _clean_title("CI Setup Guide") == "CI Setup Guide"


def test_synthesizer_needs_some_content():
    from services.agent.title_synthesizer import synthesize_conversation_title
    assert synthesize_conversation_title("", "") == ""


def test_synthesizer_uses_streamed_tokens_not_dict_keys(monkeypatch):
    # Regression: run_completion(stream=False) returns a dict; ''.join()-ing it iterates the KEYS
    # ("id","object","choices",...) → the "IDObject" title bug. Must consume stream=True tokens.
    import services.llm.llm_gateway as gw

    def _fake(prompt, **kw):
        assert kw.get("stream") is True, "title synth must stream (not join a response dict)"
        for tok in ("C ", "Variable ", "Initialization"):
            yield tok

    monkeypatch.setattr(gw, "run_completion", _fake)
    from services.agent.title_synthesizer import synthesize_conversation_title
    t = synthesize_conversation_title("best way to initialize a variable in C")
    assert t == "C Variable Initialization"
    assert "object" not in t.lower() and t != "IDObject"


def test_title_synthesis_flag_default_on():
    import runtime_safety
    assert runtime_safety.load_config().get("conversation_title_synthesis_enabled") is True


def test_llm_title_cleaner_rejects_bare_aspect_name():
    # Round-11: a title completion that degenerated to only an echoed speaker tag ("Morrigan:" /
    # "⚔ Morrigan:") survived _strip_leading_speaker_label's "never nuke" guard and was rstripped to
    # "Morrigan" — the aspect name leaking as the conversation title. Must collapse to "" instead.
    from services.agent.title_synthesizer import _clean_title
    assert _clean_title("Morrigan:") == ""
    assert _clean_title("⚔ Morrigan:") == ""
    assert _clean_title("Nyx") == ""
    # A real topic that merely starts with the aspect label is still cleaned to the topic.
    assert _clean_title("Morrigan: Auth Refactor") == "Auth Refactor"


def test_clean_title_strips_midstring_title_prefix():
    # The 3B echoes "…Title: X" mid-line; the real title is after the LAST Title:/Topic: marker.
    from services.agent.title_synthesizer import _clean_title
    assert _clean_title("Hi there Mina How are you Title: Hi there, how are you") == "Hi there, how are you"
    assert _clean_title("Paris is capital France Title: Paris France Capital") == "Paris France Capital"


def test_clean_title_strips_reference_and_bleed():
    from services.agent.title_synthesizer import _clean_title
    assert "REFERENCE" not in _clean_title("Morrigan greets. ### REFERENCE")
    out = _clean_title("Hi there. This is a written TEXT chat: you are typing")
    assert "written TEXT chat" not in out and out.strip()


def test_clean_title_caps_words_and_length():
    from services.agent.title_synthesizer import _MAX_TITLE_LEN, _MAX_TITLE_WORDS, _clean_title
    out = _clean_title("The Best Way to Reverse a String in Python Using Slicing and Loops for Beginners")
    assert len(out.split()) <= _MAX_TITLE_WORDS and len(out) <= _MAX_TITLE_LEN
