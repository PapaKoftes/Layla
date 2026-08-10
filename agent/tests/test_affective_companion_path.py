"""Regression tests for the companion emotional-support path.

Context: the GF conversation exposed that an "I'm in emotional pain" message was routed to the
task/coding blade under an anti-warmth output-discipline and came back clinical (advice lists,
"draft a message", "seek counseling"), and kept doing it after the user said to stop. The fix:
a distress detector routes affective turns to the warm aspect (Echo) and flips the output
discipline to warmth-first. These tests lock that chain in place.
"""
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from services.personality.affect_detect import is_affective_turn

# --- detector ---------------------------------------------------------------

def test_distress_and_relationship_messages_are_affective():
    assert is_affective_turn(
        "i am in deep emotional pain due to my relationship. i started having doubts on "
        "whether or not my girlfriend really has room for me"
    )
    assert is_affective_turn("I feel so alone and I just need to vent")
    assert is_affective_turn("me and my girlfriend broke up and I'm heartbroken")
    assert is_affective_turn("I need reassurance, I feel like I don't matter")
    assert is_affective_turn("i'm falling apart and I can't take this anymore")


def test_technical_messages_are_not_affective():
    # The trap: "feel like" / "hurts" in an engineering context must NOT trip the detector.
    assert not is_affective_turn("write a python function that reverses a linked list")
    assert not is_affective_turn("I feel like this code is wrong, the function hurts performance")
    assert not is_affective_turn("the build broke and the tests are failing")
    assert not is_affective_turn("what can you do?")
    assert not is_affective_turn("")
    assert not is_affective_turn(None)  # type: ignore[arg-type]


# --- routing ----------------------------------------------------------------

def test_affective_turn_routes_to_echo():
    import orchestrator as O

    asp = O.select_aspect(
        "i am in deep emotional pain, my girlfriend and I are drifting apart and it's breaking me"
    )
    assert asp.get("id") == "echo"
    assert asp.get("_affective_turn") is True


def test_technical_turn_does_not_route_by_affect():
    import orchestrator as O

    asp = O.select_aspect("write a python function that reverses a linked list")
    # Not forced to echo by the affect gate (no _affective_turn marker).
    assert not asp.get("_affective_turn")


# --- output discipline ------------------------------------------------------

def test_output_discipline_flips_to_warmth_first_on_affective():
    from services.prompts import system_head_builder as SHB

    warm = SHB._append_output_discipline("You are Echo.", {}, affective=True)
    cold = SHB._append_output_discipline("You are Morrigan.", {}, affective=False)

    # Warmth-first block: present + reassurance welcome, no clinical lead.
    assert "PRESENT" in warm and "Reassurance is welcome" in warm
    assert "numbered plan" in warm  # the "do NOT lead with a numbered plan/draft" guard
    # The terse/anti-warmth default clause must be gone on affective turns...
    assert "don't force warmth" not in warm
    # ...but still present on ordinary task turns.
    assert "don't force warmth" in cold
