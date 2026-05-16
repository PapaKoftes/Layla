# -*- coding: utf-8 -*-
"""
test_frame_modifier.py -- Unit tests for FRAME calibration system.

Tests stat -> prompt modifier conversion, combination rules,
snapshot I/O, and integration with user_identity format.

Run:
    cd agent/ && python -m pytest tests/test_frame_modifier.py -v
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

AGENT_DIR = Path(__file__).resolve().parent.parent
if str(AGENT_DIR) not in sys.path:
    sys.path.insert(0, str(AGENT_DIR))

from services.frame_modifier import (
    _HIGH,
    _LOW,
    build_frame_block,
    build_frame_modifiers,
    load_profile_snapshot,
    load_stats_from_identity,
    write_profile_snapshot,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _stats(**kwargs) -> dict[str, int]:
    base = {k: 5 for k in ("technical", "creative", "analytical", "social", "patience", "ambition")}
    base.update(kwargs)
    return base


# ---------------------------------------------------------------------------
# Neutral profile -- no modifiers
# ---------------------------------------------------------------------------

def test_neutral_profile_no_hints():
    hints = build_frame_modifiers(_stats())
    assert hints == [], "All-5 profile should produce no modifiers"


def test_neutral_profile_empty_block():
    block = build_frame_block(_stats())
    assert block == ""


def test_empty_stats_no_hints():
    assert build_frame_modifiers({}) == []


# ---------------------------------------------------------------------------
# Single-stat rules
# ---------------------------------------------------------------------------

def test_high_technical():
    hints = build_frame_modifiers(_stats(technical=_HIGH))
    assert any("fluency" in h.lower() and "high" in h.lower() for h in hints)


def test_low_technical():
    hints = build_frame_modifiers(_stats(technical=_LOW))
    assert any("low" in h.lower() and ("fluency" in h.lower() or "jargon" in h.lower()) for h in hints)


def test_high_patience():
    hints = build_frame_modifiers(_stats(patience=_HIGH))
    assert any("thorough" in h.lower() for h in hints)


def test_low_patience():
    hints = build_frame_modifiers(_stats(patience=_LOW))
    assert any("concise" in h.lower() for h in hints)


def test_high_ambition():
    hints = build_frame_modifiers(_stats(ambition=_HIGH))
    assert any("ambition" in h.lower() or "stretch" in h.lower() for h in hints)


def test_low_ambition():
    hints = build_frame_modifiers(_stats(ambition=_LOW))
    assert any("scope" in h.lower() or "incremental" in h.lower() for h in hints)


def test_high_creative():
    hints = build_frame_modifiers(_stats(creative=_HIGH))
    assert any("creative" in h.lower() or "unconventional" in h.lower() for h in hints)


def test_low_creative():
    hints = build_frame_modifiers(_stats(creative=_LOW))
    assert any("proven" in h.lower() or "standard" in h.lower() for h in hints)


def test_high_analytical():
    hints = build_frame_modifiers(_stats(analytical=_HIGH))
    assert any("quantif" in h.lower() or "risk" in h.lower() for h in hints)


def test_low_analytical():
    hints = build_frame_modifiers(_stats(analytical=_LOW))
    assert any("light" in h.lower() or "practical" in h.lower() for h in hints)


def test_high_social():
    hints = build_frame_modifiers(_stats(social=_HIGH))
    assert any("people" in h.lower() or "collaboration" in h.lower() for h in hints)


def test_low_social():
    hints = build_frame_modifiers(_stats(social=_LOW))
    assert any("solo" in h.lower() or "individual" in h.lower() for h in hints)


# ---------------------------------------------------------------------------
# Combination rules
# ---------------------------------------------------------------------------

def test_architect_mode_high_tech_analytical():
    hints = build_frame_modifiers(_stats(technical=_HIGH, analytical=_HIGH))
    assert any("architect" in h.lower() or "system" in h.lower() for h in hints)


def test_fast_track_high_ambition_low_patience():
    hints = build_frame_modifiers(_stats(ambition=_HIGH, patience=_LOW))
    assert any("fast" in h.lower() or "decisive" in h.lower() for h in hints)


def test_deep_dive_high_patience_analytical():
    hints = build_frame_modifiers(_stats(patience=_HIGH, analytical=_HIGH))
    joined = " ".join(hints).lower()
    assert "deep" in joined or "thorough" in joined or "full reasoning" in joined


def test_guided_teaching_low_tech_high_patience():
    hints = build_frame_modifiers(_stats(technical=_LOW, patience=_HIGH))
    joined = " ".join(hints).lower()
    assert "teach" in joined or "guided" in joined or "steps" in joined


def test_narrative_high_social_creative():
    hints = build_frame_modifiers(_stats(social=_HIGH, creative=_HIGH))
    joined = " ".join(hints).lower()
    assert "narrat" in joined or "analogi" in joined or "story" in joined


def test_strategic_high_ambition_analytical():
    hints = build_frame_modifiers(_stats(ambition=_HIGH, analytical=_HIGH))
    joined = " ".join(hints).lower()
    assert "strategic" in joined or "leverage" in joined or "impact" in joined


# ---------------------------------------------------------------------------
# Cap enforcement
# ---------------------------------------------------------------------------

def test_max_hints_cap():
    # All stats at extremes -> many rules fire; must be capped
    extreme = _stats(
        technical=10, creative=10, analytical=10,
        social=10, patience=10, ambition=10,
    )
    hints = build_frame_modifiers(extreme, max_hints=3)
    assert len(hints) <= 3


def test_default_cap_is_six():
    extreme = _stats(
        technical=10, creative=10, analytical=10,
        social=10, patience=10, ambition=10,
    )
    hints = build_frame_modifiers(extreme)
    assert len(hints) <= 6


# ---------------------------------------------------------------------------
# build_frame_block format
# ---------------------------------------------------------------------------

def test_block_starts_with_header():
    block = build_frame_block(_stats(technical=_HIGH))
    assert block.startswith("Behavioral calibration:")


def test_block_uses_bullet_lines():
    block = build_frame_block(_stats(patience=_LOW))
    assert "\n- " in block


def test_block_empty_when_neutral():
    assert build_frame_block(_stats()) == ""


# ---------------------------------------------------------------------------
# load_stats_from_identity
# ---------------------------------------------------------------------------

def test_load_from_identity_all_present():
    uid = {
        "stat_technical": "8",
        "stat_creative": "3",
        "stat_analytical": "7",
        "stat_social": "5",
        "stat_patience": "9",
        "stat_ambition": "2",
    }
    stats = load_stats_from_identity(uid)
    assert stats["technical"] == 8
    assert stats["creative"] == 3
    assert stats["patience"] == 9


def test_load_from_identity_missing_defaults_to_5():
    stats = load_stats_from_identity({})
    for sid in ("technical", "creative", "analytical", "social", "patience", "ambition"):
        assert stats[sid] == 5


def test_load_from_identity_clamps():
    uid = {"stat_technical": "99", "stat_patience": "-5"}
    stats = load_stats_from_identity(uid)
    assert stats["technical"] == 10
    assert stats["patience"] == 1


# ---------------------------------------------------------------------------
# Profile snapshot I/O
# ---------------------------------------------------------------------------

def test_write_and_load_snapshot(tmp_path, monkeypatch):
    import services.frame_modifier as fm
    monkeypatch.setattr(fm, "_PROFILE_PATH", tmp_path / ".layla" / "layla_profile.json")

    uid = {
        "stat_technical": "9",
        "stat_patience": "3",
        "stat_ambition": "8",
        "stat_creative": "5",
        "stat_analytical": "5",
        "stat_social": "5",
        "maturity_xp": "120",
        "maturity_rank": "2",
        "maturity_phase": "growth",
        "goals_summary": "Build leverage.",
    }
    write_profile_snapshot(uid)

    snap = load_profile_snapshot()
    assert snap["stats"]["technical"] == 9
    assert snap["stats"]["patience"] == 3
    assert len(snap["active_modifiers"]) > 0
    assert snap["maturity"]["phase"] == "growth"
    assert "goals_summary" in snap["prefs"]
    assert "generated_at" in snap


def test_snapshot_active_modifiers_match_build(tmp_path, monkeypatch):
    import services.frame_modifier as fm
    monkeypatch.setattr(fm, "_PROFILE_PATH", tmp_path / "profile.json")

    uid = {"stat_technical": "8", "stat_patience": "2"}
    write_profile_snapshot(uid)
    snap = load_profile_snapshot()

    stats = load_stats_from_identity(uid)
    direct = build_frame_modifiers(stats)
    assert snap["active_modifiers"] == direct


def test_load_snapshot_missing_returns_empty(tmp_path, monkeypatch):
    import services.frame_modifier as fm
    monkeypatch.setattr(fm, "_PROFILE_PATH", tmp_path / "nonexistent.json")
    assert load_profile_snapshot() == {}


def test_write_snapshot_bad_path_does_not_raise(monkeypatch):
    import services.frame_modifier as fm
    monkeypatch.setattr(fm, "_PROFILE_PATH", Path("/impossible/path/x/y/z/profile.json"))
    # Should not raise -- errors are swallowed
    write_profile_snapshot({"stat_technical": "8"})
