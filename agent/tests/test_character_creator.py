"""Tests for character creator service and router."""

import json
from unittest.mock import MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from services.character_creator import (
    ALL_ASPECTS,
    ASPECT_DEFAULTS,
    EARNABLE_TITLES,
    PERSONALITY_TRAITS,
    VOICE_PARAMS,
    get_available_titles,
    personality_to_prompt_hints,
)
from routers.character import router

app = FastAPI()
app.include_router(router)
client = TestClient(app)


# ── Service-level tests ──────────────────────────────────────────────────────

def test_all_aspects_count():
    """Must have exactly 6 aspects."""
    assert len(ALL_ASPECTS) == 6


def test_all_aspects_are_strings():
    """All aspect IDs are lowercase strings."""
    for aid in ALL_ASPECTS:
        assert isinstance(aid, str)
        assert aid == aid.lower()


def test_aspect_defaults_keys():
    """Every aspect must have defaults with required fields."""
    required_keys = {
        "name", "title", "symbol", "tagline",
        "color_primary", "color_glow",
        "voice_pitch", "voice_speed", "voice_warmth", "voice_formality",
        "personality_aggression", "personality_humor", "personality_verbosity",
        "personality_curiosity", "personality_bluntness", "personality_empathy",
        "lore_origin", "lore_philosophy", "unlocked",
    }
    for aid in ALL_ASPECTS:
        assert aid in ASPECT_DEFAULTS, f"Missing defaults for {aid}"
        d = ASPECT_DEFAULTS[aid]
        for key in required_keys:
            assert key in d, f"Missing key '{key}' in defaults for {aid}"


def test_personality_traits_metadata():
    """PERSONALITY_TRAITS has all 6 traits with correct structure."""
    assert len(PERSONALITY_TRAITS) == 6
    for t in PERSONALITY_TRAITS:
        assert "id" in t
        assert "label" in t
        assert "min" in t
        assert "max" in t
        assert t["max"] > t["min"]


def test_voice_params_metadata():
    """VOICE_PARAMS has 4 params with correct structure."""
    assert len(VOICE_PARAMS) == 4
    for v in VOICE_PARAMS:
        assert "id" in v
        assert "label" in v
        assert "step" in v


def test_earnable_titles_all_aspects():
    """Every aspect has at least 1 earnable title."""
    for aid in ALL_ASPECTS:
        assert aid in EARNABLE_TITLES
        assert len(EARNABLE_TITLES[aid]) >= 1


def test_earnable_titles_default_rank_zero():
    """Each aspect has at least one title unlocked at rank 0."""
    for aid in ALL_ASPECTS:
        rank0_titles = [t for t in EARNABLE_TITLES[aid] if t.get("rank_req", 0) == 0]
        assert len(rank0_titles) >= 1, f"No rank-0 title for {aid}"


def test_get_available_titles_rank_filter():
    """get_available_titles filters by rank."""
    titles_r0 = get_available_titles("morrigan", 0)
    titles_r5 = get_available_titles("morrigan", 5)
    titles_r10 = get_available_titles("morrigan", 10)
    assert len(titles_r0) >= 1
    assert len(titles_r10) >= len(titles_r5) >= len(titles_r0)


def test_get_available_titles_unknown_aspect():
    """Unknown aspect returns empty list."""
    assert get_available_titles("unknown_aspect", 10) == []


def test_personality_to_prompt_hints_returns_list():
    """personality_to_prompt_hints returns a list of strings."""
    with patch("services.character_creator.load_aspect_profile") as mock_load:
        mock_load.return_value = {
            "ok": True,
            "personality_aggression": 9,
            "personality_humor": 1,
            "personality_verbosity": 9,
            "personality_curiosity": 1,
            "personality_bluntness": 10,
            "personality_empathy": 1,
        }
        hints = personality_to_prompt_hints("morrigan")
    assert isinstance(hints, list)
    assert len(hints) > 0
    for h in hints:
        assert isinstance(h, str)


def test_personality_to_prompt_hints_center_values():
    """Center values (5) should produce no hints."""
    with patch("services.character_creator.load_aspect_profile") as mock_load:
        mock_load.return_value = {
            "ok": True,
            "personality_aggression": 5,
            "personality_humor": 5,
            "personality_verbosity": 5,
            "personality_curiosity": 5,
            "personality_bluntness": 5,
            "personality_empathy": 5,
        }
        hints = personality_to_prompt_hints("morrigan")
    assert isinstance(hints, list)
    assert len(hints) == 0


# ── Router-level tests ───────────────────────────────────────────────────────

def test_get_traits():
    """GET /character/traits returns trait metadata."""
    r = client.get("/character/traits")
    assert r.status_code == 200
    data = r.json()
    assert "traits" in data
    assert len(data["traits"]) == 6


def test_get_voice_params():
    """GET /character/voice-params returns voice metadata."""
    r = client.get("/character/voice-params")
    assert r.status_code == 200
    data = r.json()
    assert "params" in data
    assert len(data["params"]) == 4


def test_get_earnable_titles():
    """GET /character/earnable-titles returns all titles."""
    r = client.get("/character/earnable-titles")
    assert r.status_code == 200
    data = r.json()
    for aid in ALL_ASPECTS:
        assert aid in data


def test_get_aspect_invalid():
    """GET /character/aspects/invalid returns 400."""
    r = client.get("/character/aspects/not_real")
    assert r.status_code == 400


def test_get_aspect_valid():
    """GET /character/aspects/morrigan returns profile."""
    r = client.get("/character/aspects/morrigan")
    assert r.status_code == 200
    data = r.json()
    # Should have at least the default fields
    assert data.get("name") == "Morrigan" or data.get("ok") is True


def test_get_titles_for_aspect():
    """GET /character/aspects/morrigan/titles returns titles."""
    r = client.get("/character/aspects/morrigan/titles")
    assert r.status_code == 200
    data = r.json()
    assert "titles" in data
    assert len(data["titles"]) >= 1


def test_get_prompt_hints():
    """GET /character/aspects/echo/prompt-hints returns hints."""
    r = client.get("/character/aspects/echo/prompt-hints")
    assert r.status_code == 200
    data = r.json()
    assert "hints" in data
    assert isinstance(data["hints"], list)


def test_get_tutorial():
    """GET /character/tutorial returns tutorial state."""
    r = client.get("/character/tutorial")
    assert r.status_code == 200
    data = r.json()
    assert "wizard_complete" in data
    assert "tutorial_step" in data
    assert "main_aspect" in data


def test_patch_aspect_no_changes():
    """PATCH /character/aspects/morrigan with no changes returns ok."""
    r = client.patch("/character/aspects/morrigan", json={})
    assert r.status_code == 200
    data = r.json()
    assert data["ok"] is True
    assert data["saved_keys"] == []


def test_patch_aspect_invalid():
    """PATCH /character/aspects/bad_id returns 400."""
    r = client.patch("/character/aspects/bad_id", json={"personality_aggression": 7})
    assert r.status_code == 400


def test_reset_aspect_invalid():
    """POST /character/aspects/bad_id/reset returns 400."""
    r = client.post("/character/aspects/bad_id/reset")
    assert r.status_code == 400


def test_set_title_missing_title():
    """POST /character/aspects/morrigan/title with no title returns 400."""
    r = client.post("/character/aspects/morrigan/title", json={})
    assert r.status_code == 400


def test_set_main_aspect_invalid():
    """POST /character/main-aspect with invalid aspect returns error."""
    r = client.post("/character/main-aspect", json={"aspect_id": "invalid"})
    assert r.status_code == 200  # still returns JSON
    data = r.json()
    assert data.get("ok") is False


def test_tutorial_advance():
    """POST /character/tutorial/advance advances step."""
    r = client.post("/character/tutorial/advance", json={"step": 3})
    assert r.status_code == 200
    data = r.json()
    assert data.get("ok") is True
    assert data.get("step") == 3


def test_tutorial_advance_invalid_step():
    """POST /character/tutorial/advance with step > 99 fails validation."""
    r = client.post("/character/tutorial/advance", json={"step": 200})
    assert r.status_code == 422  # Pydantic validation


def test_summary_endpoint():
    """GET /character/summary returns structured data."""
    r = client.get("/character/summary")
    assert r.status_code == 200
    data = r.json()
    # Should have tutorial and aspects
    assert "tutorial" in data or "aspects" in data or "ok" in data


def test_list_all_aspects():
    """GET /character/aspects returns all 6 profiles."""
    r = client.get("/character/aspects")
    assert r.status_code == 200
    data = r.json()
    assert isinstance(data, dict)
    for aid in ALL_ASPECTS:
        assert aid in data
