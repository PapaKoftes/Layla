"""Regression: the [EARNED_TITLE: …] marker must not leak into user-facing answers."""
from __future__ import annotations

from services.agent.response_builder import strip_junk_from_reply


def test_trailing_earned_title_stripped():
    assert strip_junk_from_reply("365 [EARNED_TITLE: Water Wizard]") == "365"


def test_trailing_earned_title_with_fence():
    assert strip_junk_from_reply("Rust [EARNED_TITLE: Water Wizard]\n```") == "Rust"


def test_leading_earned_title_still_stripped():
    assert strip_junk_from_reply("[EARNED_TITLE: X] Paris") == "Paris"


def test_midline_earned_title_stripped():
    assert strip_junk_from_reply("The answer is [EARNED_TITLE: Y] Paris") == "The answer is Paris"


def test_clean_answer_untouched():
    assert strip_junk_from_reply("The capital of France is Paris.") == "The capital of France is Paris."


def test_refused_marker_and_fence_tail_stripped():
    raw = '[EARNED_TITLE: String Wizard] The reversed string is "olleh". [REFUSED: no more] ```\n\n\ns\n```'
    assert strip_junk_from_reply(raw) == 'The reversed string is "olleh".'


def test_degenerate_fence_loop_collapses_to_empty():
    assert strip_junk_from_reply("[EARNED_TITLE: X]\n```\n\n\ns\n```\n\ns\n```") == ""


def test_objective_echo_cut():
    # Round-16 #1: "Objective:" is a common word (OKRs, charters), so the cut must be conservative —
    # only a LINE-ANCHORED "Objective:" that co-occurs with an UNAMBIGUOUS sibling scaffold marker is a
    # leaked prompt echo. A lone / inline "Objective:" is legit content and is PRESERVED.
    assert strip_junk_from_reply(
        "Here is the answer.\nObjective: research capital\nCurrent goal: research capital"
    ) == "Here is the answer."
    # Lone / inline "Objective:" (no sibling scaffold) is kept — no more truncating an OKR/charter.
    assert strip_junk_from_reply("The answer is Paris. Objective: Research capital") == "The answer is Paris. Objective: Research capital"
    assert strip_junk_from_reply("Objective: grow revenue.\nKey results: 1) x 2) y") == "Objective: grow revenue.\nKey results: 1) x 2) y"


def test_echo_patterns_marker_cut():
    assert strip_junk_from_reply("The capital of France is Paris.\nEcho (patterns/preferences):") == "The capital of France is Paris."
    assert strip_junk_from_reply('The reversed string is "olleh".\nECHO: internal') == 'The reversed string is "olleh".'


def test_bracketed_echo_marker_cut():
    # Golden-eval live-probe finding: the marker leaked wrapped in brackets, which the
    # old `(?:^|\s)` guard missed because `[` precedes "Echo" (regression fix).
    assert strip_junk_from_reply("[Echo (patterns/preferences): title]") == ""
    assert strip_junk_from_reply("The capital of France is Paris. [Echo (patterns/preferences): brevity]") == "The capital of France is Paris."
    assert strip_junk_from_reply("[ECHO: internal note] leaked") == ""
    # Conservative: a mid-line `echo:` in legit shell content must NOT be stripped.
    assert strip_junk_from_reply("To print: echo: hello world") == "To print: echo: hello world"


def test_leading_active_aspect_marker_preserves_answer():
    # Golden-eval live-probe finding: a weak model prepended [EARNED_TITLE: …] and
    # [Active aspect: …] before the real answer. [Active aspect: …] used to truncate the
    # whole reply to end (dropping the answer → strip returned "" → /v1 kept the raw leak).
    # It must now be removed like EARNED_TITLE, preserving the answer that follows.
    assert strip_junk_from_reply(
        "[EARNED_TITLE: Water boiling at sea level]\n\n[Active aspect: Morrigan]\nWater boils at 100 C."
    ) == "Water boils at 100 C."
    assert strip_junk_from_reply("[Active aspect: Nyx]\nParis.") == "Paris."
    # A *trailing* system-head echo (real content first) must still be cut.
    assert strip_junk_from_reply("The answer is 42.\nCurrent goal: solve stuff") == "The answer is 42."
