"""
A2 — the settings editor must not confirm writes that will not apply.

Ten of the ninety editable settings are OWNED by hardware auto-tune, which overwrites them on
every config load (runtime_safety.load_config -> apply_auto_tune). Editing one returned a
blanket {"ok": true} and the value was silently reverted before anything read it. Only ONE of
the ten carried a warning. The documented escape hatch, auto_tune_locked_keys, was not a
schema key, so it was unreachable from both the UI and the API.

These tests pin: the ten are marked, the escape hatch is real, and POST /settings reports what
it rejected and what auto-tune will overwrite — following the /settings/appearance pattern.
"""
from __future__ import annotations

import json

import pytest

import config_schema as cs
from services.infrastructure.auto_tune import PROFILE_KEYS, apply_auto_tune

# The exact ten, as measured. Written out rather than recomputed so a change to either side
# (PROFILE_KEYS or EDITABLE_SCHEMA) has to be noticed by a human instead of silently agreeing
# with itself.
TEN = {
    "n_ctx", "n_batch", "n_gpu_layers", "n_threads", "hyde_enabled", "performance_mode",
    "enable_self_reflection", "completion_max_tokens", "max_runtime_seconds",
    "tool_call_timeout_seconds",
}


@pytest.fixture()
def cfg_file(tmp_path, monkeypatch):
    """Point runtime_safety at a throwaway config so no test can touch operator state."""
    import runtime_safety as rs

    p = tmp_path / "runtime_config.json"
    p.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(rs, "CONFIG_FILE", p)
    rs.invalidate_config_cache()
    yield p
    rs.invalidate_config_cache()


def test_the_ten_auto_tune_owned_editable_keys():
    assert cs.auto_tune_managed_keys() == TEN


def test_schema_marks_who_owns_each_field():
    """The UI cannot warn about a key it is not told about."""
    fields = {f["key"]: f for f in cs.get_schema_for_api()["fields"]}
    for k in TEN:
        assert fields[k].get("auto_tune_owned") is True, f"{k} is not marked as auto-tune-owned"
    assert fields["temperature"].get("auto_tune_owned") is None
    assert set(cs.get_schema_for_api()["auto_tune_owned_keys"]) == TEN


def test_auto_tune_locked_keys_is_a_reachable_schema_key():
    """It was documented in three hints as THE escape hatch and was not in EDITABLE_SCHEMA —
    so no UI control and no API write could ever set it."""
    assert "auto_tune_locked_keys" in cs.get_editable_keys()
    entry = {e["key"]: e for e in cs.EDITABLE_SCHEMA}["auto_tune_locked_keys"]
    assert entry["type"] == "list"


def test_list_values_accept_both_a_list_and_a_text_input():
    assert cs.coerce_and_clamp("auto_tune_locked_keys", "n_ctx, hyde_enabled") == ["n_ctx", "hyde_enabled"]
    assert cs.coerce_and_clamp("auto_tune_locked_keys", ["n_ctx", "n_ctx"]) == ["n_ctx"]
    assert cs.coerce_and_clamp("auto_tune_locked_keys", None) == []


def test_the_escape_hatch_actually_stops_auto_tune():
    """End of the loop: a locked key must survive apply_auto_tune."""
    base = {"auto_tune_enabled": True, "n_ctx": 32768}
    assert apply_auto_tune(base)["n_ctx"] != 32768          # unlocked -> overwritten
    locked = apply_auto_tune({**base, "auto_tune_locked_keys": ["n_ctx"]})
    assert locked["n_ctx"] == 32768                          # locked -> the user's value wins


# ── POST /settings must report, not swallow ──────────────────────────────────────
def _save(body):
    from services.infrastructure.route_helpers import sync_save_settings

    return sync_save_settings(body)


def test_unknown_key_is_reported_as_rejected(cfg_file):
    d = _save({"not_a_real_setting": 1})
    assert d["ok"] is False
    assert d["rejected"] == ["not_a_real_setting"]
    assert d["saved"] == []


def test_auto_tune_owned_write_is_reported_as_overridden(cfg_file):
    """The write lands in the file and is then reverted on load. That is neither a rejection
    nor a success, and it used to be reported as an unqualified ok:true."""
    d = _save({"n_ctx": 32768})
    assert d["saved"] == ["n_ctx"]
    assert d["overridden"] == ["n_ctx"]
    assert "auto_tune_locked_keys" in d["overridden_note"]


def test_locking_a_key_clears_the_override_warning(cfg_file):
    d = _save({"n_ctx": 32768, "auto_tune_locked_keys": ["n_ctx"]})
    assert d["ok"] is True
    assert d["overridden"] == []
    # ...and it really is locked on disk.
    assert json.loads(cfg_file.read_text())["auto_tune_locked_keys"] == ["n_ctx"]


def test_locking_a_non_auto_tune_key_is_rejected_not_silently_dropped(cfg_file):
    d = _save({"auto_tune_locked_keys": ["temperature", "n_ctx"]})
    assert d["ok"] is False
    assert d["rejected_locks"] == ["temperature"]
    assert json.loads(cfg_file.read_text())["auto_tune_locked_keys"] == ["n_ctx"]


def test_a_plain_editable_write_still_reports_clean_success(cfg_file):
    d = _save({"temperature": 0.5})
    assert d["ok"] is True and d["rejected"] == [] and d["overridden"] == []
    assert d["saved"] == ["temperature"]


def test_auto_tune_disabled_means_no_override_warning(cfg_file):
    d = _save({"auto_tune_enabled": False, "n_ctx": 32768})
    assert d["overridden"] == []
    assert d["ok"] is True


# ── the advanced-search theme could never read back as ON ────────────────────────
def test_advanced_search_theme_locks_the_key_auto_tune_would_revert():
    """hyde_enabled is forced False by auto-tune on every CPU tier, so this toggle could
    never read back as ON — inside a block whose own comment asserts "no no-op toggles"."""
    on = cs.feature_theme_updates("advanced_search", True, {})
    assert on["hyde_enabled"] is True
    assert "hyde_enabled" in on["auto_tune_locked_keys"]

    # And the theme now genuinely survives a config load on a CPU tier.
    merged = apply_auto_tune({"auto_tune_enabled": True, **on})
    assert merged["hyde_enabled"] is True, "the advanced-search toggle still cannot stay on"


def test_turning_the_theme_off_hands_the_key_back_to_auto_tune():
    off = cs.feature_theme_updates("advanced_search", False, {"auto_tune_locked_keys": ["hyde_enabled", "n_ctx"]})
    assert off["hyde_enabled"] is False
    assert off["auto_tune_locked_keys"] == ["n_ctx"], "an unrelated lock must not be dropped"


def test_theme_without_managed_flags_does_not_touch_the_lock_list():
    upd = cs.feature_theme_updates("remote_access", True, {})
    assert "auto_tune_locked_keys" not in upd


def test_themes_report_which_of_their_flags_auto_tune_owns():
    themes = {t["key"]: t for t in cs.get_feature_themes({})}
    assert themes["advanced_search"]["managed_flags"] == ["hyde_enabled"]
    assert themes["remote_access"]["managed_flags"] == []


def test_profile_keys_and_schema_have_not_drifted():
    """If a new auto-tune key becomes editable, it must be added to TEN deliberately —
    otherwise it joins the set of controls that lie, unnoticed."""
    assert PROFILE_KEYS & cs.get_editable_keys() == TEN
