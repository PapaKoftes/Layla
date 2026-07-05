"""BL-092: user-created custom aspects — additive over the 6 built-ins."""
from __future__ import annotations

from services.personality import custom_aspects as ca
from services.personality.character_creator import (
    ALL_ASPECTS,
    all_aspect_ids,
    load_aspect_profile,
    set_main_aspect,
)

_SPEC = {
    "id": "sable",
    "name": "Sable",
    "symbol": "☾",
    "tagline": "quiet, nocturnal, precise",
    "base_aspect": "nyx",
    "prompt_hint": "Speak softly and favour concise, exact answers.",
    "color_primary": "#3a2a5a",
}


def test_create_lists_and_resolves(monkeypatch):
    r = ca.save_custom_aspect(_SPEC)
    assert r["ok"] is True and r["aspect"]["id"] == "sable"

    # shows up in the roster, after the 6 built-ins
    ids = all_aspect_ids()
    assert list(ids)[: len(ALL_ASPECTS)] == list(ALL_ASPECTS)
    assert "sable" in ids

    # profile inherits nyx defaults, overrides name/symbol/prompt
    prof = load_aspect_profile("sable")
    assert prof["ok"] is True
    assert prof["name"] == "Sable" and prof["symbol"] == "☾"
    assert prof["base_aspect"] == "nyx" and prof["custom"] is True
    assert prof.get("voice_pitch") is not None  # inherited from base nyx defaults

    # can be set as the main aspect
    assert set_main_aspect("sable")["ok"] is True

    assert ca.delete_custom_aspect("sable") is True
    assert "sable" not in all_aspect_ids()


def test_builtins_untouched():
    # The 6 built-ins resolve exactly as before, regardless of custom aspects.
    for aid in ALL_ASPECTS:
        p = load_aspect_profile(aid)
        assert p["ok"] is True and not p.get("custom")


def test_validation():
    assert ca.save_custom_aspect({"id": "Bad Id!"})["ok"] is False       # bad id
    assert ca.save_custom_aspect({"id": "morrigan"})["ok"] is False       # built-in collision
    assert ca.save_custom_aspect({"id": "x9", "base_aspect": "nope"})["ok"] is False  # bad base
    assert load_aspect_profile("does_not_exist")["ok"] is False


def test_router_endpoints():
    """The /character/custom-aspects endpoints round-trip (create -> list -> delete)."""
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from routers import character as ch
    app = FastAPI(); app.include_router(ch.router)
    client = TestClient(app)

    r = client.post("/character/custom-aspects", json={"id": "vesper", "name": "Vesper", "base_aspect": "echo", "symbol": "✵"})
    assert r.status_code == 200 and r.json()["ok"] is True
    lst = client.get("/character/custom-aspects").json()
    assert len(lst["base_aspects"]) == 6
    assert any(c["id"] == "vesper" for c in lst["custom"])
    assert client.delete("/character/custom-aspects/vesper").json()["ok"] is True
