"""Guard for the revived mood system (C5): the turn loop must nudge mood, high-precision.

Previously `register_signal` only ever fired from the (unsurfaced) 👍/👎 UI, so mood stayed
permanently neutral and `mood_hint` injected nothing. `register_from_turn` wires the turn loop:
the user's sentiment (praise/correction/frustration) + a failed task outcome move mood; a
plain successful turn does NOT (else mood pins warm on every trivial reply).
"""
import sys
from pathlib import Path

AGENT_DIR = Path(__file__).resolve().parent.parent
if str(AGENT_DIR) not in sys.path:
    sys.path.insert(0, str(AGENT_DIR))


def _ep():
    import services.personality.emotional_presence as ep
    ep.reset()
    return ep


def test_praise_warms_mood():
    ep = _ep()
    ep.register_from_turn("thanks, that's perfect")
    assert ep.current_mood()["valence"] > 0.1


def test_correction_cools_mood():
    ep = _ep()
    for msg in ("no, that is wrong", "that is not what i asked", "it doesnt work", "you are wrong"):
        ep.reset()
        ep.register_from_turn(msg)
        assert ep.current_mood()["valence"] < 0, msg


def test_no_false_positive_on_neutral_or_positive_phrases():
    ep = _ep()
    for msg in ("no problem at all", "no worries", "yes that works", "the capital is Paris", "can you help me"):
        ep.reset()
        ep.register_from_turn(msg)
        assert ep.current_mood()["label"] == "steady", msg


def test_plain_success_does_not_pin_mood_positive():
    ep = _ep()
    ep.register_from_turn("what is 2 + 2?", outcome_success=True)
    assert ep.current_mood()["label"] == "steady"


def test_failed_outcome_subdues_mood():
    ep = _ep()
    ep.register_from_turn("build the thing", outcome_success=False)
    assert ep.current_mood()["valence"] < 0


def test_flag_default_on():
    # mood must inject by default now (was read but never set → defaulted off)
    import runtime_safety
    cfg = runtime_safety.load_config()
    assert cfg.get("emotional_presence_enabled") is True
