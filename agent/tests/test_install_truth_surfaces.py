"""
N2/N3/N6 — the surfaces that report what happened must not contradict the disk.

Three defects of one family, all of the shape "the call succeeded and the outcome is false":

  N2  the marketplace "✓ installed" badge was derived from CONFIG FLAGS alone, so immediately
      after a failed Voice install the kit card read "installed" while the chat toolbar on the
      SAME PAGE read "Voice isn't installed".
  N3  save_config_keys did `cfg[k] = coerce_and_clamp(k, v)` then `saved.append(k)` without
      ever comparing the two. Typing 500 into Max tool calls (max 50) produced a GREEN
      "Settings saved" with 50 on disk; {"max_tool_calls": "not-a-number"} produced
      {"ok": true, "saved": [...]} with the value silently becoming the schema default.
  N6  POST /settings pops remote-protected keys from the body BEFORE sync_save_settings
      computes `rejected`, so a remote operator got {"ok": true} for a REFUSED write.
"""
from __future__ import annotations

import json

import pytest

import runtime_safety as rs
from services.infrastructure.route_helpers import sync_save_settings


@pytest.fixture()
def cfg_file(tmp_path, monkeypatch):
    p = tmp_path / "runtime_config.json"
    p.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(rs, "CONFIG_FILE", p)
    rs.invalidate_config_cache()
    yield p
    rs.invalidate_config_cache()


def _disk(cfg_file) -> dict:
    return json.loads(cfg_file.read_text(encoding="utf-8"))


# ── N2: an "installed" badge must consult the packages, not just the flags ───────
def test_kit_badge_is_not_installed_when_the_packages_are_absent(monkeypatch):
    """The live contradiction: flags on (the wizard wrote them), packages absent (the install
    failed), badge said "✓ installed"."""
    from services.skills import kit_catalog

    monkeypatch.setattr("install.feature_installer.dep_present", lambda dep: False)
    status = kit_catalog.installed_status({
        "voice_stt_prewarm_enabled": True, "voice_tts_prewarm_enabled": True,
    })
    assert status["voice-companion"] is False


def test_kit_badge_is_installed_when_flags_and_packages_agree(monkeypatch):
    from services.skills import kit_catalog

    monkeypatch.setattr("install.feature_installer.dep_present", lambda dep: True)
    status = kit_catalog.installed_status({
        "voice_stt_prewarm_enabled": True, "voice_tts_prewarm_enabled": True,
    })
    assert status["voice-companion"] is True


def test_kit_badge_is_not_installed_when_packages_are_there_but_flags_are_off(monkeypatch):
    """Present-but-disabled is not "installed" either — the badge means usable."""
    from services.skills import kit_catalog

    monkeypatch.setattr("install.feature_installer.dep_present", lambda dep: True)
    assert kit_catalog.installed_status({})["voice-companion"] is False


def test_flagless_kit_still_resolves(monkeypatch):
    """A kit whose features carry no deps (Connected → `remote`) must not be dragged to False
    by a package check that has nothing to check."""
    from services.skills import kit_catalog

    monkeypatch.setattr("install.feature_installer.dep_present", lambda dep: False)
    assert kit_catalog.installed_status({"remote_enabled": True})["connected"] is True


# ── N3: a clamped or coerced value is not a clean save ───────────────────────────
def test_out_of_range_value_is_reported_as_clamped(cfg_file):
    """The exact live repro: 500 into Max tool calls (max 50) → green "Settings saved (90)",
    field shows 500, disk holds 50."""
    out = sync_save_settings({"max_tool_calls": 500})

    assert _disk(cfg_file)["max_tool_calls"] == 50, "clamping itself must still happen"
    adjusted = {a["key"]: a for a in out["adjusted"]}
    assert "max_tool_calls" in adjusted, "a value rewritten on the way to disk was reported as a clean save"
    assert adjusted["max_tool_calls"]["reason"] == "clamped"
    assert adjusted["max_tool_calls"]["requested"] == 500
    assert adjusted["max_tool_calls"]["stored"] == 50
    assert "max_tool_calls" in out["adjusted_note"]


def test_unparseable_value_is_reported_as_coerced(cfg_file):
    """{"max_tool_calls": "not-a-number"} answered {"ok": true, "saved": ["max_tool_calls"]}
    while the value silently became the schema default."""
    out = sync_save_settings({"max_tool_calls": "not-a-number"})

    adjusted = {a["key"]: a for a in out["adjusted"]}
    assert adjusted["max_tool_calls"]["reason"] == "coerced"
    assert adjusted["max_tool_calls"]["stored"] == _disk(cfg_file)["max_tool_calls"]


def test_an_in_range_value_is_a_clean_save(cfg_file):
    """The counterweight: an honoured value must NOT be flagged, or the warning becomes noise
    and gets ignored exactly like the always-on auto-tune one did."""
    out = sync_save_settings({"max_tool_calls": 7})
    assert out["adjusted"] == []
    assert out["saved"] == ["max_tool_calls"]
    assert _disk(cfg_file)["max_tool_calls"] == 7


def test_type_equivalent_input_is_not_reported_as_adjusted(cfg_file):
    """A number arriving as a string from a text input, or a bool as "true", is the same value
    — reporting those would bury the two cases that matter."""
    out = sync_save_settings({"max_tool_calls": "7", "safe_mode": "true"})
    assert out["adjusted"] == [], out["adjusted"]


@pytest.mark.parametrize("value,reason", [(500, "clamped"), (-99, "clamped"), ("junk", "coerced")])
def test_describe_adjustment_names_the_reason(value, reason):
    from config_schema import coerce_and_clamp, describe_adjustment

    stored = coerce_and_clamp("max_tool_calls", value)
    assert describe_adjustment("max_tool_calls", value, stored) == reason


# ── N7: warn only about settings that are not in force ───────────────────────────
def test_the_warning_fires_on_effective_disagreement_not_on_a_file_diff(cfg_file):
    """N7's requirement was "don't warn about keys the operator didn't touch" — an always-on
    warning is wallpaper and gets ignored exactly when it matters.

    It was IMPLEMENTED as a diff against the FILE (`res["changed"]`), and that is S1(b): the
    control is rendered from the EFFECTIVE config, so in the steady state after any wizard
    apply — file == request, effective != request — the key is not "changed" and the warning
    went silent in the one case it exists for. Re-posting a value that has never once applied
    is not "no change"; it is the same lie, told again.

    The anti-wallpaper guarantee survives, delivered by the honest mechanism: a key that IS in
    force never warns however often it is posted, and a key that is NOT in force warns every
    time — including when the file already agrees with the request.
    """
    cfg_file.write_text(json.dumps({"auto_tune_enabled": True, "n_ctx": 4096}), encoding="utf-8")
    rs.invalidate_config_cache()

    # Auto-tune re-derives n_ctx, so the stored 4096 has never been in force.
    d = sync_save_settings({"n_ctx": 4096})
    assert d["changed"] == [], "precondition: the file already holds the requested value"
    assert d["overridden"] == ["n_ctx"], "silenced in exactly the state it exists for"

    # In force → silent, on every save. This is the wallpaper N7 removed, and it stays removed.
    assert sync_save_settings({"temperature": 0.5})["overridden"] == []
    assert sync_save_settings({"temperature": 0.5})["overridden"] == []
    # …and the escape hatch still ends the warning for real.
    assert sync_save_settings({"n_ctx": 8192, "auto_tune_locked_keys": ["n_ctx"]})["overridden"] == []


# ── N6: a refused remote write is not a success ──────────────────────────────────
def test_remote_blocked_keys_are_reported_as_rejected(cfg_file):
    """POST /settings strips these before calling us, so they were invisible to `rejected` and
    a refused write came back {"ok": true} with a green toast."""
    out = sync_save_settings({"temperature": 0.5}, blocked_keys=["safe_mode", "sandbox_root"])

    assert out["ok"] is False
    assert "safe_mode" in out["rejected"] and "sandbox_root" in out["rejected"]
    assert out["refused_remote"] == ["safe_mode", "sandbox_root"]
    assert "only be changed from the machine" in out["error"]
    # The permitted key in the same request still lands.
    assert _disk(cfg_file)["temperature"] == 0.5


def test_local_write_is_unaffected(cfg_file):
    out = sync_save_settings({"temperature": 0.5})
    assert out["ok"] is True
    assert out["rejected"] == [] and "refused_remote" not in out


def test_post_settings_reports_the_refusal_end_to_end(cfg_file, monkeypatch):
    """Through the real endpoint, with the request looking remote — the surface the operator
    actually sees."""
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from routers import settings as settings_router

    monkeypatch.setattr("services.safety.auth.is_direct_local", lambda headers, host: False)
    app = FastAPI()
    app.include_router(settings_router.router)
    d = TestClient(app).post("/settings", json={"safe_mode": False, "temperature": 0.4}).json()

    assert d["ok"] is False
    assert "safe_mode" in d["rejected"]
    assert "safe_mode" not in _disk(cfg_file), "a refused key must not reach the config"


def test_two_refusals_in_one_request_both_survive(cfg_file):
    """A remote refusal and a bad lock in the same body: assigning `error` twice dropped the
    first message, and a security refusal is not something to lose to a formatting bug."""
    out = sync_save_settings(
        {"auto_tune_locked_keys": ["temperature"]}, blocked_keys=["safe_mode"],
    )
    assert out["ok"] is False
    assert "safe_mode" in out["error"], "the remote refusal was erased by the lock error"
    assert "temperature" in out["error"]
