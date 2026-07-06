"""#1 root-cause: the system head ends with an output-discipline instruction so weak
models don't echo internal scaffolding ([EARNED_TITLE]/[TOOL]/Objective:/Echo) back."""
from __future__ import annotations

from services.prompts import system_head_builder as shb


def test_discipline_appended_by_default():
    head = shb._append_output_discipline("You are Layla.", {})
    assert "Output discipline" in head
    assert "[EARNED_TITLE]" in head and "Echo (patterns/preferences)" in head
    assert head.startswith("You are Layla.")   # appended, not prepended


def test_discipline_can_be_disabled():
    head = shb._append_output_discipline("You are Layla.", {"output_discipline_enabled": False})
    assert head == "You are Layla."


def test_discipline_is_the_tail():
    # it must be the LAST thing the model reads (highest instruction recency)
    head = shb._append_output_discipline("SYSTEM\n\nsome context", {})
    assert head.rstrip().endswith("Just give the answer.")
