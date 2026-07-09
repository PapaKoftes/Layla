"""Phase 2 voice guard: the FRAME axes must encode the calibrated antihero register.

The North Star's FRAME vector (EDGE/NERVE/SIGNAL/IRON/…) never existed in code — a generic
competency quiz shipped instead, so nothing told the model to be blunt or push back and the
voice flattened to corporate-warm. This pins the rebuilt FRAME: seeded to "direct + keep some
warmth" out-of-box (profile beats defaults), operator-overridable, and reaching the prompt.
"""
import sys
from pathlib import Path

AGENT_DIR = Path(__file__).resolve().parent.parent
if str(AGENT_DIR) not in sys.path:
    sys.path.insert(0, str(AGENT_DIR))


def test_seeded_defaults_are_direct_plus_warmth():
    from services.personality.frame_modifier import _FRAME_DEFAULTS
    # direct + pushback + short, but warmth kept (IRON neutral, not full logic-first)
    assert _FRAME_DEFAULTS["edge"] >= 7 and _FRAME_DEFAULTS["nerve"] >= 7
    assert _FRAME_DEFAULTS["signal"] <= 4
    assert _FRAME_DEFAULTS["iron"] == 5  # neutral → keeps emotional acknowledgment / warmth


def test_block_fires_out_of_box_with_edge():
    from services.personality.frame_modifier import build_frame_block, load_stats_from_identity
    block = build_frame_block(load_stats_from_identity({})).lower()
    assert "behavioral calibration" in block
    assert "be direct" in block and "lead with the answer" in block   # EDGE
    assert "push back" in block                                        # NERVE
    assert "short by default" in block                                 # SIGNAL
    # IRON neutral → no logic-first suppression of warmth
    assert "logic-first" not in block and "minimize reassurance" not in block


def test_operator_override_softens():
    from services.personality.frame_modifier import build_frame_block, load_stats_from_identity
    soft = build_frame_block(load_stats_from_identity({"stat_edge": "2", "stat_nerve": "2"})).lower()
    assert "soften delivery" in soft
    assert "push back" not in soft


def test_voice_reaches_built_head():
    # the guaranteed voice signal (output-discipline closer) must carry the direct register on
    # every substantive turn, regardless of section-budget truncation on low tiers.
    import orchestrator
    from services.prompts.system_head_builder import build_system_head
    asp = orchestrator.select_aspect("refactor this function", force_aspect="morrigan")
    head = build_system_head(goal="refactor this function", aspect=asp, reasoning_mode="deep").lower()
    assert "lead with the answer" in head
    assert "when the operator is wrong" in head
    assert "not cold or robotic" in head
