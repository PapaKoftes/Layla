"""BL-190: emotional presence — decaying mood, signals, prompt hint."""
from __future__ import annotations

import pytest

from services.personality import emotional_presence as ep


@pytest.fixture(autouse=True)
def _tmp(tmp_path, monkeypatch):
    monkeypatch.setattr(ep, "_db_path", lambda: tmp_path / "mood.db")


def test_starts_steady():
    m = ep.current_mood(now=1000.0)
    assert m["label"] == "steady" and m["valence"] == 0.0


def test_praise_warms_mood():
    ep.register_signal("praise", now=1000.0)
    m = ep.current_mood(now=1000.0)
    assert m["valence"] > 0 and m["energy"] > 0.5
    assert "warm" in m["label"] or "content" in m["label"]


def test_correction_tenses_mood():
    ep.register_signal("correction", now=1000.0)
    m = ep.current_mood(now=1000.0)
    assert m["valence"] < 0 and m["energy"] > 0.5
    assert "tense" in m["label"]


def test_mood_decays_toward_neutral():
    t0 = 1_000_000.0
    ep.register_signal("failure", now=t0)
    hot = ep.current_mood(now=t0)["valence"]
    # ~24h later (4 half-lives at 6h) → strongly decayed toward 0
    cooled = ep.current_mood(now=t0 + 24 * 3600.0)["valence"]
    assert abs(cooled) < abs(hot) / 4


def test_signals_accumulate():
    ep.register_signal("praise", now=1000.0)
    ep.register_signal("praise", now=1000.0)
    two = ep.current_mood(now=1000.0)["valence"]
    ep.reset()
    ep.register_signal("praise", now=1000.0)
    one = ep.current_mood(now=1000.0)["valence"]
    assert two > one


def test_hint_empty_when_steady_else_present():
    assert ep.mood_hint(now=1000.0) == ""
    ep.register_signal("frustration", now=1000.0)
    hint = ep.mood_hint(now=1000.0)
    assert hint and "mood" in hint and "persona" in hint


def test_values_clamped():
    for _ in range(20):
        ep.register_signal("praise", now=1000.0)
    m = ep.current_mood(now=1000.0)
    assert m["valence"] <= 1.0 and m["energy"] <= 1.0


def test_feedback_nudges_mood(tmp_path, monkeypatch):
    # a 👍 through answer_feedback should warm the mood
    from services.infrastructure import answer_feedback as af
    monkeypatch.setattr(af, "_db_path", lambda: tmp_path / "fb.db")
    monkeypatch.setattr(ep, "_db_path", lambda: tmp_path / "mood.db")
    af.record_feedback("up")
    assert ep.current_mood()["valence"] > 0
