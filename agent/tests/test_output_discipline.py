"""#1 root-cause: the system head ends with an output-discipline instruction so weak
models don't echo internal scaffolding (bracketed control tags / Objective: / section
headers) back. The instruction must NOT enumerate the specific marker tokens — naming
them primes a small model to emit them (the 'don't think of an elephant' effect)."""
from __future__ import annotations

from services.prompts import system_head_builder as shb


def test_discipline_appended_by_default():
    head = shb._append_output_discipline("You are Layla.", {})
    assert "Output discipline" in head
    # Instructs plain prose with no bracketed control tags / section headers …
    assert "bracketed control tags" in head and "plain conversational prose" in head
    # … but must NOT spell out the exact marker names (that priming caused the leaks).
    assert "[EARNED_TITLE]" not in head and "[TOOL]" not in head
    assert head.startswith("You are Layla.")   # appended, not prepended


def test_discipline_can_be_disabled():
    head = shb._append_output_discipline("You are Layla.", {"output_discipline_enabled": False})
    assert head == "You are Layla."


def test_discipline_is_the_tail():
    # it must be the LAST thing the model reads (highest instruction recency)
    head = shb._append_output_discipline("SYSTEM\n\nsome context", {})
    tail = head.rstrip()
    # ends on DIRECT, not "warm" — this closer is the guaranteed voice signal that survives
    # budget truncation on low tiers (appended after section assembly).
    assert tail.endswith("just never perform or narrate.")
    # keeps every anti-theatrics/audio/self-name guard …
    for phrase in ("Just give the answer.", "theatrical", "typing, not speaking", "Match length"):
        assert phrase in tail
    # … and carries the calibrated direct+warmth voice (lead with answer, warmth earned, pushback)
    for phrase in ("lead with the answer", "warmth is", "when the operator is wrong", "not cold or robotic"):
        assert phrase.lower() in tail.lower(), phrase
