"""Regression: the reply sanitizer must not flatten a multi-line reply onto one line.

Bug A (reported from hands-on use): "messages display properly while streaming but once the
streaming is finished the formatting and spacing is gone." Root cause: _collapse_repetition split
the reply on sentence boundaries (which include the newline after each sentence) and rejoined with
a single space, so every numbered list / multi-paragraph reply collapsed to one run-on line. The
client swaps the server's cleaned `content` in on the done frame, so the flattened text replaced the
correctly-formatted streamed text. These tests lock newline preservation in while keeping the
genuine loop-collapse behavior.
"""
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from services.agent.response_builder import _collapse_repetition, strip_junk_from_reply


def _strip_junk(text):
    try:
        return strip_junk_from_reply(text)
    except TypeError:
        return strip_junk_from_reply(text, {})


NUMBERED_LIST = (
    "To sleep better, focus on relaxation and consistency.\n"
    "1. Establish a regular bedtime routine.\n"
    "2. Create a relaxing environment with minimal light and noise.\n"
    "3. Avoid screens for at least an hour before bed.\n\n"
    "Follow these tips to enhance your sleep quality."
)

MULTI_PARAGRAPH = (
    "I really hear how much pain you're in right now. That matters.\n\n"
    "It's okay to feel uncertain about all of this. Take your time.\n\n"
    "Tell me whatever you want. I'm here."
)


def test_collapse_repetition_preserves_list_newlines():
    out = _collapse_repetition(NUMBERED_LIST)
    # No repetition here → returned verbatim (stripped), every newline intact.
    assert out == NUMBERED_LIST.strip()
    assert out.count("\n") >= 4


def test_collapse_repetition_preserves_paragraph_breaks():
    out = _collapse_repetition(MULTI_PARAGRAPH)
    assert out.count("\n\n") == 2


def test_full_sanitizer_preserves_list_newlines():
    out = _strip_junk(NUMBERED_LIST)
    assert out.count("\n") >= 4
    assert "1. Establish" in out and "2. Create" in out


def test_parroted_hardware_directive_is_stripped():
    # A weak model parrots the injected "[Hardware: … | tier: potato] Running on constrained…" tail.
    leaked = (
        "To sleep better, focus on consistency.\n"
        "1. Keep a regular bedtime.\n"
        "2. Dim the lights before bed.\n"
        "3. Avoid screens for an hour before sleep.\n\n"
        "Follow these to rest better.\n\n"
        "[Hardware: 15 GB RAM, CPU-only | sub-1B (very small) model | context window: 2048 tokens | "
        "tier: potato] Running on constrained hardware with a small model. Context window is tight."
    )
    out = _strip_junk(leaked)
    assert "[Hardware:" not in out
    assert "constrained hardware" not in out
    # ...without collateral damage to the real answer's formatting.
    assert out.count("\n") >= 4 and "1. Keep a regular bedtime" in out


def test_legit_hardware_mention_without_tier_is_kept():
    # Ordinary prose that happens to say "[Hardware: …]" (no tier: directive signature) must survive.
    legit = (
        "I set up your new [Hardware: GPU] rig notes. " * 3
        + "Everything is documented and ready for you to review now."
    )
    assert "[Hardware: GPU]" in _strip_junk(legit)


def test_greeting_loop_still_collapses():
    loop = (
        "Hi there! How can I help you today? Hey, what do you need help with? "
        "Hello again, could you clarify what you want? Greetings, please specify your request."
    )
    out = _collapse_repetition(loop)
    assert len(out) < len(loop)
    assert out.lower().startswith("hi there")


def test_repeated_sentence_loop_still_collapses():
    rep = (
        "The capital of France is Paris. It is a lovely city with great food. "
        "The capital of France is Paris. The capital of France is Paris. "
        "The capital of France is Paris."
    )
    out = _collapse_repetition(rep)
    assert len(out) < len(rep)
    assert out.count("Paris") <= 2
