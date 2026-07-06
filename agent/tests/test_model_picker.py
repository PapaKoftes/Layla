"""Task 1: install model picker — uncensored-first, hardware-filtered, companion-aware."""
from __future__ import annotations

from install import model_selector as ms


def test_picker_puts_uncensored_first():
    p = ms.models_for_picker(16.0, 0, uncensored_first=True)
    # the first viable entries must all be uncensored
    top = [m for m in p["models"] if m["viable"]][:8]
    assert top and all(m["uncensored"] for m in top)


def test_picker_marks_viability_by_ram():
    p = ms.models_for_picker(8.0, 0)
    for m in p["models"]:
        # a 40GB model can't be viable on an 8GB box
        if m["ram_required"] > 8.0 / 0.9 + 0.01:
            assert not m["viable"], m["name"]


def test_recommended_is_uncensored_companion_and_fits():
    p = ms.models_for_picker(16.9, 0)
    rec = next(m for m in p["models"] if m["recommended"])
    assert rec["uncensored"] and rec["viable"]
    assert rec["category"] in {"general", "creative", "fast"}   # not a coder/reasoning specialist


def test_recommend_uncensored_helper():
    r = ms.recommend_uncensored_model(16.9)
    assert r and r["uncensored"] and r["viable"]


def test_uncensored_first_toggle_off_keeps_all():
    on = ms.models_for_picker(64.0, 0, uncensored_first=True)
    off = ms.models_for_picker(64.0, 0, uncensored_first=False)
    assert {m["filename"] for m in on["models"]} == {m["filename"] for m in off["models"]}
    # with a big RAM budget the restricted models still appear, just not first
    assert any(not m["uncensored"] for m in off["models"])
