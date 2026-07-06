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
    assert strip_junk_from_reply("The answer is Paris. Objective: Research capital") == "The answer is Paris."


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
