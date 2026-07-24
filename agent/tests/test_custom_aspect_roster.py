"""BL-301b — a custom aspect must be FIRST-CLASS once created.

THE DEFECT. You could open the Ctrl+K "create custom aspect" overlay, make `Sable`, press
"talk as this" — and then the name resolved nowhere else in the product. The custom aspect lived
only in `user_identity` rows; the roster every other surface reads (`orchestrator._load_aspects()`,
which is the source for the aspect bar, `@mention`, `/aspects/{id}`, the OpenAI-compat model list
and the deliberation roster) was built exclusively from `personalities/*.json`. Six names in, six
names out. So the aspect existed, was persisted, was selectable from exactly one overlay, and was
invisible to everything else.

WHAT THESE TESTS PIN, and how each one goes red if the fix is reverted:

  (a) resolves via @mention          -> `resolve_aspect_ref('@sable')` returns None (roster has 6)
  (b) appears in the rendered roster -> `aspect_roster()` has 6 rows, no 'sable'
  (c) survives a reload              -> `reload_aspects()` drops back to 6 built-ins
  (d) a built-in is never shadowed   -> a custom NAMED "Morrigan" would win the name lookup

The JS half of the same contract (the bar buttons + the @mention dropdown/resolver reading one
merged roster) is executed in Node by test_custom_aspect_roster_ui.py.
"""
from __future__ import annotations

import pytest

import orchestrator
from services.personality import custom_aspects as ca
from services.personality.character_creator import ALL_ASPECTS, all_aspect_ids

_SABLE = {
    "id": "sable",
    "name": "Sable",
    "symbol": "☾",
    "tagline": "quiet, nocturnal, precise",
    "base_aspect": "nyx",
    "prompt_hint": "Speak softly and favour concise, exact answers.",
    "color_primary": "#3a2a5a",
}


@pytest.fixture
def sable():
    """Create the custom aspect, hand back its id, always clean up."""
    r = ca.save_custom_aspect(dict(_SABLE))
    assert r["ok"] is True, r
    try:
        yield r["aspect"]["id"]
    finally:
        ca.delete_custom_aspect("sable")
        orchestrator.invalidate_aspects_cache()


def _ids(rows):
    return [str(a.get("id")) for a in rows]


# ── (a) @mention ─────────────────────────────────────────────────────────────

def test_custom_aspect_resolves_via_mention_by_id_and_by_name(sable):
    """`@sable` and `@Sable` must both land on the custom aspect."""
    assert ca.resolve_aspect_ref("@sable") == "sable"
    assert ca.resolve_aspect_ref("sable") == "sable"
    assert ca.resolve_aspect_ref("Sable") == "sable"      # display name, any case
    assert ca.resolve_aspect_ref("  @SABLE  ") == "sable"  # the input box is not tidy


def test_mention_resolution_still_reports_a_real_miss(sable):
    """The custom path must not turn every typo into a silent match."""
    assert ca.resolve_aspect_ref("@not_an_aspect_zzz") is None
    assert ca.resolve_aspect_ref("") is None
    assert ca.resolve_aspect_ref(None) is None


def test_builtin_mentions_are_untouched(sable):
    for aid in ALL_ASPECTS:
        assert ca.resolve_aspect_ref("@" + aid) == aid


# ── (b) the roster the bar renders ───────────────────────────────────────────

def test_custom_aspect_is_in_the_roster_the_bar_renders(sable):
    rows = ca.aspect_roster()
    ids = [r["id"] for r in rows]
    assert ids[: len(ALL_ASPECTS)] == list(ALL_ASPECTS), (
        "the 6 built-ins must stay first and in order — that ordering IS the collision rule"
    )
    assert "sable" in ids, "custom aspect missing from the roster the aspect bar renders"
    row = next(r for r in rows if r["id"] == "sable")
    assert row["name"] == "Sable" and row["symbol"] == "☾" and row["custom"] is True
    assert row["base_aspect"] == "nyx"


def test_custom_aspect_is_in_the_orchestrator_roster_with_the_base_persona(sable):
    """The bar/@mention roster and the roster the MODEL is built from are the same list."""
    aspects = orchestrator.reload_aspects()
    ids = _ids(aspects)
    assert "sable" in ids, "custom aspect absent from orchestrator._load_aspects()"
    assert ids.index("sable") >= len(ALL_ASPECTS), "custom aspects must come after the built-ins"
    a = next(x for x in aspects if x.get("id") == "sable")
    assert a.get("custom") is True and a.get("base_aspect") == "nyx"
    assert a.get("name") == "Sable"
    # inherits the base persona, and the operator's hint is appended to it
    nyx = next(x for x in aspects if x.get("id") == "nyx")
    assert a.get("triggers") == nyx.get("triggers")
    assert "Speak softly" in (a.get("systemPromptAddition") or "")


def test_all_aspect_ids_matches_the_roster(sable):
    assert "sable" in all_aspect_ids()


# ── (c) persistence across a reload / restart ────────────────────────────────

def test_custom_aspect_survives_a_reload(sable):
    """A restart re-reads the DB, so a hard cache drop is the honest in-process proxy for it."""
    assert "sable" in _ids(orchestrator.reload_aspects())

    # Simulate the process coming back up: every in-memory cache gone, nothing but the DB left.
    orchestrator.invalidate_aspects_cache()
    assert orchestrator._ASPECTS_CACHE is None, "cache was not actually dropped — the test is vacuous"

    after = orchestrator.reload_aspects()
    assert "sable" in _ids(after), "custom aspect did not survive the reload"
    assert ca.resolve_aspect_ref("@sable") == "sable"
    assert "sable" in [r["id"] for r in ca.aspect_roster()]


def test_create_invalidates_the_cache_so_the_name_resolves_immediately():
    """Without the invalidation the roster is stale for up to _ASPECTS_TTL (60s) — i.e. you create
    an aspect and it still resolves nowhere, which is the original bug with a timer on it."""
    orchestrator.reload_aspects()          # warm the cache WITHOUT the new aspect in it
    assert orchestrator._ASPECTS_CACHE is not None
    assert ca.resolve_aspect_ref("vesper") is None
    try:
        assert ca.save_custom_aspect({"id": "vesper", "name": "Vesper", "base_aspect": "echo"})["ok"] is True
        assert ca.resolve_aspect_ref("vesper") == "vesper", "stale roster — create did not invalidate"
        assert ca.resolve_aspect_ref("Vesper") == "vesper"
    finally:
        ca.delete_custom_aspect("vesper")
        orchestrator.invalidate_aspects_cache()
    assert ca.resolve_aspect_ref("vesper") is None, "delete did not invalidate the roster"


# ── (d) collisions must never shadow a built-in ──────────────────────────────

def test_a_custom_named_like_a_builtin_does_not_shadow_it():
    """The operator may call their aspect "Morrigan". `@morrigan` must still be THE Morrigan."""
    r = ca.save_custom_aspect({
        "id": "morri", "name": "Morrigan", "base_aspect": "eris",
        "prompt_hint": "IMPOSTOR_MARKER_4471",
    })
    assert r["ok"] is True
    try:
        assert ca.resolve_aspect_ref("@morrigan") == "morrigan", "a custom aspect shadowed a built-in name"
        assert ca.resolve_aspect_ref("Morrigan") == "morrigan"
        assert ca.resolve_aspect_ref("morri") == "morri", "the custom is still reachable by its own id"

        rows = ca.aspect_roster()
        assert [r_["id"] for r_ in rows][: len(ALL_ASPECTS)] == list(ALL_ASPECTS)

        # and the persona actually handed to the model for @morrigan is the built-in one
        got = orchestrator.select_aspect("refactor this", force_aspect="morrigan")
        assert got.get("id") == "morrigan" and not got.get("custom")
        assert "IMPOSTOR_MARKER_4471" not in (got.get("systemPromptAddition") or "")
    finally:
        ca.delete_custom_aspect("morri")
        orchestrator.invalidate_aspects_cache()


def test_an_id_colliding_with_a_builtin_is_refused_at_creation():
    assert ca.save_custom_aspect({"id": "morrigan", "name": "Not Morrigan"})["ok"] is False
    assert ca.save_custom_aspect({"id": "lilith"})["ok"] is False


def test_a_forged_row_with_a_builtin_id_cannot_enter_the_roster(monkeypatch):
    """Defence in depth: even if a row with a built-in id reaches the DB (a hand-edited value, an
    older build), the merge must drop it rather than let it replace the built-in persona."""
    forged = [{"id": "morrigan", "name": "Impostor", "base_aspect": "eris",
               "prompt_hint": "FORGED_MARKER_8802", "custom": True}]
    monkeypatch.setattr(ca, "list_custom_aspects", lambda: forged)
    aspects = orchestrator.reload_aspects()
    try:
        morrigans = [a for a in aspects if a.get("id") == "morrigan"]
        assert len(morrigans) == 1, "the forged row created a SECOND morrigan in the roster"
        assert not morrigans[0].get("custom")
        assert "FORGED_MARKER_8802" not in (morrigans[0].get("systemPromptAddition") or "")
    finally:
        monkeypatch.undo()
        orchestrator.invalidate_aspects_cache()


# ── invalid / empty names ────────────────────────────────────────────────────

def test_blank_and_control_character_names_get_a_usable_fallback():
    """A whitespace-only name used to be stored verbatim and rendered as an unclickable blank chip."""
    try:
        r = ca.save_custom_aspect({"id": "wisp", "name": "   ", "base_aspect": "echo"})
        assert r["ok"] is True and r["aspect"]["name"] == "Wisp"
        assert ca.resolve_aspect_ref("Wisp") == "wisp"
    finally:
        ca.delete_custom_aspect("wisp")

    # A one-character name would score +5 in select_aspect's name pass on nearly every message and
    # quietly hijack auto-routing, so it falls back to the id the same way a blank one does.
    try:
        r = ca.save_custom_aspect({"id": "kestrel", "name": "K", "base_aspect": "eris"})
        assert r["ok"] is True and r["aspect"]["name"] == "Kestrel"
    finally:
        ca.delete_custom_aspect("kestrel")

    try:
        r = ca.save_custom_aspect({"id": "night_owl", "name": "Night\nOwl\t", "base_aspect": "nyx"})
        assert r["ok"] is True
        assert r["aspect"]["name"] == "Night Owl", "control characters must not reach the bar label"
        assert ca.resolve_aspect_ref("night_owl") == "night_owl"
        assert ca.resolve_aspect_ref("Night Owl") == "night_owl"
    finally:
        ca.delete_custom_aspect("night_owl")
        orchestrator.invalidate_aspects_cache()


def test_invalid_ids_are_still_refused():
    for bad in ("", "  ", "A", "9lives", "has space", "Bad Id!", "x" * 40):
        assert ca.save_custom_aspect({"id": bad})["ok"] is False, f"accepted invalid id {bad!r}"


def test_builtins_still_load_when_no_custom_aspects_exist():
    """The merge must be additive — with an empty custom set the roster is exactly the 6."""
    aspects = orchestrator.reload_aspects()
    assert sorted(a["id"] for a in aspects if not a.get("custom")) == sorted(ALL_ASPECTS)
