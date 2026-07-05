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
