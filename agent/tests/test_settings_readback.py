"""
S1/S2/S3 — the read-back principle, applied to POST /settings.

WHY THIS FILE EXISTS, GIVEN A GREEN 3716-TEST GATE

test_settings_honesty.py already drove POST /settings and asserted that an auto-tune-owned
write comes back flagged. It passed, and the endpoint still returned a clean green success for
a value that is reverted before anything reads it, because both the code and the test shared
two assumptions:

  (a) ONE OWNER WAS ENUMERATED. The report was
          [k for k in changed if k in auto_tune_managed_keys() and k not in locked]
      — a hardcoded owner list. runtime_safety.MATURITY_GATED_KEYS reverts keys by the same
      mechanism and appears nowhere in it, so
          POST {"inline_initiative_enabled": true}
      answered ok:true, overridden:[], rejected:[], adjusted:[] with the value False in force.
      Every test in the class asked about auto-tune, so none of them could see it.

  (b) THE `changed` FILTER SILENCED THE WARNING WHERE IT MATTERS MOST. `changed` compares the
      request against the FILE; the control is rendered from the EFFECTIVE config. In the
      STEADY STATE after any wizard apply — file == request, effective != request — the key is
      not "changed", so the one case the warning exists for was the one case it suppressed.
      The existing tests all wrote to an EMPTY config, where file != request is guaranteed, so
      the steady state was never reached.

So the tests here assert on EFFECTIVE state via a SECOND save of the same value, and cover the
owner nobody has written a probe for: an unrecognised owner must still produce an honest
"did not take effect", never a silent green.
"""
from __future__ import annotations

import json

import pytest

from install.feature_status import key_owner
from install.setup_profiles import flag_satisfied


@pytest.fixture()
def cfg_file(tmp_path, monkeypatch):
    """Throwaway config — no test may touch operator state."""
    import runtime_safety as rs

    p = tmp_path / "runtime_config.json"
    p.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(rs, "CONFIG_FILE", p)
    rs.invalidate_config_cache()
    yield p
    rs.invalidate_config_cache()


@pytest.fixture()
def cpu_tier(monkeypatch):
    """Pin auto-tune to a CPU tier so the outcome does not depend on the runner's hardware.

    Stubs the PROFILE, not the flags, so the real apply_auto_tune overlay stays in the path.
    """
    import services.infrastructure.auto_tune as at

    monkeypatch.setattr(
        at, "compute_optimization_profile",
        lambda *a, **k: {"hyde_enabled": False, "n_ctx": 2048, "_opt_tier": "potato"},
    )


def _save(body):
    from services.infrastructure.route_helpers import sync_save_settings

    return sync_save_settings(dict(body))


def _effective():
    import runtime_safety as rs

    rs.invalidate_config_cache()
    return dict(rs.load_config())


def _row(d, key):
    return next(r for r in d["report"] if r["key"] == key)


# ── S1(a): the owner that was never enumerated ──────────────────────────────────
@pytest.mark.parametrize("key", [
    "inline_initiative_enabled",
    "initiative_engine_enabled",
    "autonomous_mode",
    "initiative_project_proposals_enabled",
    "autonomy_optimizer_enabled",
])
def test_a_formerly_rank_gated_write_now_takes_effect(cfg_file, key):
    """INVERTED FROM test_maturity_reverted_write_is_reported_as_not_in_force.

    That test pinned the old design: these keys were forced False inside load_config by
    `_apply_maturity_gates`, so the write landed on disk and the value never applied, and the
    report's job was to CONFESS that. Rank was never meant to gate features, so the honest
    outcome is no longer a well-explained failure — it is the write working.

    Teeth: asserts the effective config, not the file. If anyone reintroduces a rank overlay
    (or any other silent revert) this fails on `_effective()`, and the `took_effect` assertion
    catches the softer regression where the value reverts but the report still claims success.
    """
    d = _save({key: True})

    assert json.loads(cfg_file.read_text(encoding="utf-8"))[key] is True, "write did not land"
    assert _effective()[key] is True, (
        f"'{key}' was written True and load_config() still reads False — something is reverting "
        "it. The maturity gate used to do exactly this; it must not come back."
    )
    assert d["in_force"] is True
    assert d["overridden"] == []
    row = _row(d, key)
    assert row["outcome"] == "took_effect"
    assert row["owner"] == ""
    assert not row["reason"]


def test_the_five_settable_keys_are_actually_settable():
    """The other half of R2: a gate removed from a key nothing can write is not a fix.

    Four of the six formerly rank-gated keys had no writer at all — no schema entry, no wizard
    flag, no theme — so the product gated a feature AND offered no way to ask for it. Clearing
    the gate alone would have left them off forever with nobody to blame.
    """
    from install.feature_status import writable_config_keys

    writable = writable_config_keys()
    for key in ("inline_initiative_enabled", "initiative_engine_enabled", "autonomous_mode",
                "initiative_project_proposals_enabled", "autonomy_optimizer_enabled"):
        assert key in writable, f"'{key}' still has no in-app writer — it cannot be asked for"


def test_no_module_reintroduces_a_rank_overlay():
    """The gate is gone by NAME, not just by effect — the shapes it was built from must stay gone.

    A softer test ("autonomous_mode survives a load") would pass against a reintroduced gate set
    to a rank the test box happens to exceed. This one fails on the symbol.
    """
    import runtime_safety as rs

    for gone in ("MATURITY_GATED_KEYS", "_apply_maturity_gates", "current_maturity_rank"):
        assert not hasattr(rs, gone), (
            f"runtime_safety.{gone} is back. Maturity rank is a display of familiarity, not a "
            "capability gate — see tests/test_maturity_not_a_gate.py."
        )


def test_the_control_case_still_names_auto_tune(cfg_file, cpu_tier):
    """The one owner the old code did know must keep its precise, actionable message."""
    d = _save({"hyde_enabled": True})

    assert _effective()["hyde_enabled"] is False
    row = _row(d, "hyde_enabled")
    assert row["owner"] == "auto_tune"
    assert "auto_tune_locked_keys" in row["reason"] and "potato" in row["reason"]


# ── S1(b): the steady state, where the old filter went silent ───────────────────
def test_report_is_correct_when_file_already_equals_the_request(cfg_file, cpu_tier):
    """file == request, effective != request — the state every wizard apply leaves behind.

    The old report derived `overridden` from a diff against the FILE, so the second save of the
    same value produced changed:[] and therefore overridden:[] — a clean green success for a
    setting that has never once been in force.

    The reverting owner is auto-tune (`hyde_enabled` on the pinned CPU tier). It used to be the
    maturity gate on `inline_initiative_enabled`; that gate is deleted, so this test needed a
    real owner rather than a retired one. The subject under test is the REPORT, not the owner.
    """
    _save({"hyde_enabled": True})          # now on disk
    d = _save({"hyde_enabled": True})      # …and posted again, unchanged

    assert d["changed"] == [], "precondition: the file already holds the requested value"
    assert _effective()["hyde_enabled"] is False
    assert d["in_force"] is False, "silenced in exactly the state it exists for"
    assert _row(d, "hyde_enabled")["outcome"] == "overridden"
    assert d["overridden"] == ["hyde_enabled"]


def test_the_steady_state_holds_for_auto_tune_too(cfg_file, cpu_tier):
    """Same silence, same fix, for the owner that WAS enumerated."""
    _save({"n_ctx": 32768})
    d = _save({"n_ctx": 32768})

    assert d["changed"] == []
    assert _effective()["n_ctx"] == 2048
    assert d["overridden"] == ["n_ctx"] and d["in_force"] is False


def test_an_inference_key_is_attributed_even_though_it_is_not_a_pipeline_key(cfg_file, cpu_tier):
    """The old auto-tune probe read _PIPELINE[tier] — the pipeline-weight HALF of the profile.
    n_ctx and n_batch come from the inference half, so the probe was structurally blind to
    them; only the parallel hardcoded list in route_helpers covered them at all."""
    assert key_owner("n_ctx", _effective())[0] == "auto_tune"


# ── the backstop: an owner nobody has taught the registry about ─────────────────
def test_an_unrecognised_owner_still_reports_not_in_force(cfg_file, monkeypatch):
    """THE POINT OF THE REGISTRY, on this surface.

    A fifth owner will appear and no probe will claim it. The failure that must never return is
    the silent one: an unexplained revert reported as a clean save.
    """
    import runtime_safety as rs

    real_load = rs.load_config

    def _sabotage():
        cfg = dict(real_load())
        cfg["temperature"] = 0.11   # some owner nobody has modelled holds it here
        return cfg

    monkeypatch.setattr(rs, "load_config", _sabotage)
    d = _save({"temperature": 0.9})

    assert d["in_force"] is False, "a silent green for a value that is not in force"
    row = _row(d, "temperature")
    assert row["outcome"] == "overridden"
    assert row["owner"] == "unknown"
    assert "reason unknown" in row["reason"].lower()
    assert "did not take effect" in row["reason"].lower()
    assert row["effective"] == 0.11   # named, so the operator has something to act on


def test_unreadable_effective_config_is_unknown_not_success(cfg_file, monkeypatch):
    """If we cannot read what is in force we must say so. Falling back to "what was requested"
    is the inference this whole change deletes."""
    import runtime_safety as rs

    def _boom():
        raise OSError("config file is gone")

    monkeypatch.setattr(rs, "load_config", _boom)
    d = _save({"temperature": 0.5})

    row = _row(d, "temperature")
    assert row["outcome"] == "unknown" and row["owner"] == "unreadable"
    assert d["in_force"] is False
    assert "could not be confirmed" in row["reason"]


# ── the honest green must survive ───────────────────────────────────────────────
def test_a_write_that_really_applies_reports_took_effect(cfg_file):
    d = _save({"temperature": 0.5})

    assert d["ok"] is True and d["in_force"] is True
    assert d["overridden"] == [] and "overridden_note" not in d
    assert _row(d, "temperature") == {"key": "temperature", "requested": 0.5,
                                      "outcome": "took_effect", "owner": "", "reason": ""}


def test_a_clamped_value_that_applies_is_clamped_not_overridden(cfg_file):
    """A value rewritten to fit the schema and then genuinely in force is its own outcome —
    reporting it as `overridden` would send the operator hunting for an owner that isn't there."""
    d = _save({"temperature": 999})

    row = _row(d, "temperature")
    assert row["outcome"] == "clamped" and row["owner"] == "schema"
    assert d["in_force"] is True, "clamped-and-applied is not 'not in force'"
    assert row["requested"] == _effective()["temperature"]


def test_a_type_coerced_input_is_not_reported_as_not_in_force(cfg_file):
    """THE MIRROR-IMAGE LIE, and the one a read-back invites.

    Every value from a text input arrives as a string: "7" is stored as 7, "true" as True.
    Comparing the RAW REQUEST against the effective config makes each of those read as
    "did not take effect, reason unknown" — a false alarm on an ordinary, perfectly applied
    save. A warning that cries wolf is the wallpaper this whole report exists to replace, so
    the comparison must use the value that actually landed (post-coercion), not the request.
    """
    d = _save({"max_tool_calls": "7", "safe_mode": "true"})

    assert d["adjusted"] == [], "a type-equivalent coercion is not an adjustment"
    assert d["overridden"] == [], "a clean save reported as not-in-force"
    assert d["in_force"] is True
    assert {r["outcome"] for r in d["report"]} == {"took_effect"}
    eff = _effective()
    assert eff["max_tool_calls"] == 7 and eff["safe_mode"] is True


def test_a_list_setting_posted_as_text_is_not_a_false_alarm(cfg_file):
    """The list-typed control posts a comma-separated string; the config stores a list."""
    d = _save({"auto_tune_locked_keys": "n_ctx, hyde_enabled"})

    assert d["overridden"] == [] and d["in_force"] is True
    assert _effective()["auto_tune_locked_keys"] == ["n_ctx", "hyde_enabled"]


def test_locking_the_key_moves_it_back_to_took_effect(cfg_file, cpu_tier):
    d = _save({"n_ctx": 32768, "auto_tune_locked_keys": ["n_ctx"]})

    assert d["in_force"] is True and d["overridden"] == []
    assert _row(d, "n_ctx")["outcome"] == "took_effect"
    assert _effective()["n_ctx"] == 32768


def test_a_secret_value_is_never_echoed_back_in_the_report(cfg_file, monkeypatch):
    """The report exists to be read by a human and pasted into a bug thread. It must not carry
    the credential it just stored."""
    import runtime_safety as rs

    real_load = rs.load_config
    monkeypatch.setattr(rs, "load_config", lambda: {**real_load(), "remote_api_key": "other"})
    d = _save({"remote_api_key": "hunter2-super-secret"})

    blob = json.dumps(d)
    assert "hunter2-super-secret" not in blob and "other" not in blob


# ── S2: "does the key hold the DECLARED value", not "is it truthy" ──────────────
def test_a_truthy_but_wrong_value_does_not_satisfy_a_declared_flag():
    """The lens that proved this: a flag downgraded to a truthy-but-wrong value read as ON.
    A falsy revert was caught, so the guard looked like it worked."""
    assert flag_satisfied(True, True) is True
    for truthy_but_wrong in (1, "true", "on", "yes", [1], {"x": 1}):
        assert flag_satisfied(truthy_but_wrong, True) is False, truthy_but_wrong
    assert flag_satisfied(False, True) is False
    assert flag_satisfied(None, True) is False


def test_a_nested_flag_requirement_needs_every_declared_sub_key():
    """geometry_frameworks_enabled is a per-backend dict. A dict with one backend switched off
    is truthy, and the feature it gates is not the feature that was declared."""
    want = {"cadquery": True, "trimesh": True}
    assert flag_satisfied({"cadquery": True, "trimesh": True, "extra": False}, want) is True
    assert flag_satisfied({"cadquery": True, "trimesh": False}, want) is False
    assert flag_satisfied({"cadquery": True}, want) is False
    assert flag_satisfied(True, want) is False, "a bare bool would crash the backends"


def test_feature_status_reads_the_declared_value_not_truthiness():
    from install.feature_status import feature_status

    on = feature_status(["mcp"], cfg={"auto_tune_enabled": False, "mcp_client_enabled": True})[0]
    assert on["on"] is True

    coerced = feature_status(["mcp"], cfg={"auto_tune_enabled": False, "mcp_client_enabled": 1})[0]
    assert coerced["on"] is False, "a truthy-but-wrong value reported as a live capability"
    assert coerced["off_flags"] == ["mcp_client_enabled"]


def test_the_palette_and_the_status_report_answer_the_same_question():
    """Two readers of `flags` that disagree is the divergent-registry defect in miniature — the
    user meets both surfaces and only one of them is right."""
    from install.feature_status import feature_status
    from install.setup_profiles import enabled_feature_ids

    cfg = {"auto_tune_enabled": False, "mcp_client_enabled": 1}
    assert "mcp" not in enabled_feature_ids(cfg)
    assert feature_status(["mcp"], cfg=cfg)[0]["on"] is False


# ── ONE registry, not two ───────────────────────────────────────────────────────
def test_both_surfaces_resolve_ownership_through_the_same_registry():
    """The guard against this defect coming back. POST /settings must not grow its own owner
    list again; if it does, this import-level coupling is what breaks first."""
    import services.infrastructure.route_helpers as rh

    with open(rh.__file__, encoding="utf-8") as fh:
        src = fh.read()
    assert "from install.feature_status import" in src and "key_owner" in src, (
        "the settings surface stopped resolving ownership through install/feature_status"
    )
    # The registry answers None for a key it does not own — which every caller is required to
    # turn into an honest "did not take effect, reason unknown", never a silent green.
    assert key_owner("temperature", {"auto_tune_enabled": False}) is None


# ── C3: "not in force" is a property of the CONFIG, not of one save ─────────────
#
# WHAT REPLACED WHAT. The S3 last-mile tests asserted the UI by grepping the bundle:
#     assert "NOT in force" in SETTINGS
#     assert "#ffb454" in css
# Both passed against the defect below, for the same reason 17 text-grep tests earlier in this
# phase passed against a dead UI: the strings were present and the BEHAVIOUR was wrong. The
# panel's amber warning was drawn only from the response to a save, and saveSettings posts
# only the fields that changed, so an unrelated save produced a clean response and the warning
# was retracted — a green success beside a ticked checkbox for a setting that is not in force.
#
# These drive the sequence instead.

def _client():
    from fastapi.testclient import TestClient

    from main import app

    return TestClient(app)


def test_not_in_force_survives_a_later_unrelated_save(cfg_file, cpu_tier):
    """THE C3 SEQUENCE, step by step — the one the amber panel used to lose.

    1. save a key an owner reverts   -> reported not in force
    2. save an UNRELATED key         -> that save is clean, and says so
    3. ask the config again          -> step 1's key is STILL reported not in force

    The reverting owner is auto-tune; it was the maturity gate until that gate was deleted.
    """
    c = _client()

    r1 = c.post("/settings", json={"hyde_enabled": True}).json()
    assert r1["in_force"] is False, "step 1 must report the revert"

    n1 = c.get("/settings/not_in_force").json()
    assert n1["ok"] is True
    assert "hyde_enabled" in [r["key"] for r in n1["not_in_force"]]

    # Step 2: a different key, which really does take effect. Its response is clean — that is
    # correct and must stay correct; the no-noise guarantee is what keeps the warning credible.
    r2 = c.post("/settings", json={"max_tool_calls": 7}).json()
    assert r2["in_force"] is True
    assert [r["key"] for r in r2["report"]] == ["max_tool_calls"]

    # Step 3: THE ASSERTION THE OLD TESTS COULD NOT MAKE. The clean save above must not erase
    # the standing truth about a key it never touched.
    n2 = c.get("/settings/not_in_force").json()
    held = {r["key"]: r for r in n2["not_in_force"]}
    assert "hyde_enabled" in held, (
        "an unrelated save retracted a true not-in-force warning"
    )
    assert n2["in_force"] is False
    row = held["hyde_enabled"]
    assert row["owner"] == "auto_tune"
    assert row["requested"] is True and row["effective"] is False
    assert row["reason"]


def test_not_in_force_is_readable_without_any_save_at_all(cfg_file, cpu_tier):
    """The panel must learn this ON LOAD. Before, `key_owner` had no GET consumer anywhere —
    the only way to discover a held key was to save it, which is why reopening the panel
    showed a snapped-back checkbox and no explanation."""
    import runtime_safety as rs

    # A config that ASKS for an owned key, written with no HTTP request in sight.
    cfg_file.write_text(json.dumps({"hyde_enabled": True}), encoding="utf-8")
    rs.invalidate_config_cache()

    d = _client().get("/settings/not_in_force").json()
    assert d["ok"] is True and d["in_force"] is False
    row = next(r for r in d["not_in_force"] if r["key"] == "hyde_enabled")
    assert row["owner"] == "auto_tune" and row["effective"] is False
    assert d["note"]


def test_a_config_with_nothing_held_reports_clean(cfg_file):
    """The other half of credibility: no false alarms. A key that IS in force must never
    appear, or the panel becomes wallpaper and the operator learns to dismiss it."""
    cfg_file.write_text(json.dumps({"max_tool_calls": 7}), encoding="utf-8")
    import runtime_safety as rs

    rs.invalidate_config_cache()

    d = _client().get("/settings/not_in_force").json()
    assert d["in_force"] is True
    assert d["not_in_force"] == []


# ── C4: the toast must not report one outcome and hide the other ────────────────
def test_a_save_that_both_clamps_and_is_overridden_reports_both(cfg_file, cpu_tier):
    """C4. The UI branch order was `else if (adjusted.length)` BEFORE
    `else if (notInForce.length)`, so a clamp in the same save hid a not-in-force key from the
    toast. The panel listed it, so it was mitigated — but the toast reads as a complete
    account of the save and was not one. The server has always reported both; this pins that,
    because the client's fix depends on it."""
    d = _save({"hyde_enabled": True, "max_tool_calls": 10_000})

    assert d["adjusted"], "expected max_tool_calls to be clamped to the schema range"
    assert [a["key"] for a in d["adjusted"]] == ["max_tool_calls"]
    assert d["overridden"] == ["hyde_enabled"]
    assert d["in_force"] is False
    # Both outcomes, in one report, each with its own owner.
    assert _row(d, "max_tool_calls")["outcome"] == "clamped"
    assert _row(d, "hyde_enabled")["outcome"] == "overridden"


# ── C5: a successful keyring save must not read as "Nothing was saved" ──────────
def test_a_secret_stored_in_the_keyring_is_reported_as_saved(cfg_file, monkeypatch):
    """C5 — the same class of lie with the sign flipped.

    persist_secret_keys REMOVES the keys it stored from the body (deliberately: they must not
    reach runtime_config.json in plaintext), so a save containing only a secret produced
    saved=[] and the UI's last branch, "Nothing was saved", over a write that fully succeeded.
    A product that reports true successes as failures teaches the operator to disbelieve it,
    which costs exactly what a false success costs."""
    import services.safety.secret_store as ss

    store: dict = {}
    monkeypatch.setattr(ss, "has_keyring", lambda: True)
    monkeypatch.setattr(ss, "set_secret", lambda k, v: (store.__setitem__(k, v), True)[1])

    d = _client().post("/settings", json={"remote_api_key": "s3cret-value"}).json()

    assert store == {"remote_api_key": "s3cret-value"}, "the keyring write did not happen"
    assert d["ok"] is True
    assert "remote_api_key" in d["saved"], "a successful keyring save read as nothing saved"
    assert d["secrets_saved"] == ["remote_api_key"]
    row = _row(d, "remote_api_key")
    assert row["outcome"] == "took_effect" and row["owner"] == "keyring"
    # The plaintext must NOT be in the config file, and must not be echoed back.
    assert "remote_api_key" not in json.loads(cfg_file.read_text(encoding="utf-8"))
    assert "s3cret-value" not in json.dumps(d)


# ── C2: the themes surface, and the LAST parallel owner list ────────────────────
def test_theme_state_uses_the_declared_value_not_truthiness(cfg_file):
    """config_schema.get_feature_themes computed
        enabled = all(bool(cfg.get(k)) == bool(v) ...)
    — the truthiness comparison flag_satisfied exists to kill. A flag downgraded to a
    truthy-but-wrong value read as a live capability area."""
    from config_schema import get_feature_themes

    cfg = {"auto_tune_enabled": False, "mcp_client_enabled": True, "plugins_enabled": True}
    on = next(t for t in get_feature_themes(cfg) if t["key"] == "external_tools")
    assert on["enabled"] is True

    coerced = dict(cfg, mcp_client_enabled=1)
    off = next(t for t in get_feature_themes(coerced) if t["key"] == "external_tools")
    assert off["enabled"] is False, "a truthy-but-wrong flag reported as an enabled area"
    assert off["off_flags"] == ["mcp_client_enabled"]


def test_themes_do_not_keep_their_own_owner_list(cfg_file):
    """THE POINT OF C2. `managed = auto_tune_managed_keys() & set(t["flags"])` was a hardcoded
    single-owner list — byte-for-byte the shape route_helpers had just deleted, and blind to
    MATURITY_GATED_KEYS and security_policy. Ownership here must come from the ONE registry.

    Asserted over the AST, not the text. The first draft of this test grepped for the deleted
    expression and failed on the COMMENT that documents its deletion — a string-matching test
    reporting a defect that is not there, which is the same failure mode (a text grep standing
    in for a fact about behaviour) as the S3 tests this file replaced, with the sign flipped.
    """
    import ast

    import config_schema

    with open(config_schema.__file__, encoding="utf-8") as fh:
        tree = ast.parse(fh.read())

    theme_fns = [n for n in ast.walk(tree)
                 if isinstance(n, ast.FunctionDef)
                 and n.name in ("get_feature_themes", "feature_theme_updates")]
    assert len(theme_fns) == 2

    called = set()
    for fn in theme_fns:
        for node in ast.walk(fn):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
                called.add(node.func.id)
    assert "key_owner" in called, "themes stopped asking the shared owner registry"
    assert "auto_tune_managed_keys" not in called, (
        "the parallel single-owner list is back — ownership must come from key_owner"
    )


def test_a_theme_flag_an_owner_holds_is_reported_with_that_owner(cfg_file, monkeypatch):
    """A theme flag held by an owner OTHER than auto-tune must be named. The old hardcoded
    `auto_tune_managed_keys() & flags` intersection could not see one, so it reported nothing.

    HOW THIS IS DRIVEN, AND WHY IT CHANGED. It used to borrow the maturity gate as its
    non-auto-tune owner. That gate is deleted, and with it the last owner that reverts a key
    *at config load* — security_policy and external_credential describe write-path refusals and
    credential state, so neither can produce an asked-for key that load_config flips back.
    Rewriting the test around auto-tune would have deleted the only thing it checks.

    So the second owner is INJECTED into the real registry instead of borrowed from whichever
    owners happen to exist today. That is strictly closer to the property under test — "this
    code asks `_KEY_OWNERS`, it does not intersect a hardcoded list" — and it keeps holding when
    the set of live owners changes again.
    """
    import config_schema
    import install.feature_status as fs
    from config_schema import get_feature_themes

    def _fake_owner(key, cfg):
        return ("test_owner", "a probe registered in the registry claimed this key") \
            if key == "hyde_enabled" else None

    monkeypatch.setattr(fs, "_KEY_OWNERS", [_fake_owner, *fs._KEY_OWNERS])

    theme = dict(next(t for t in config_schema.FEATURE_THEMES if t["key"] == "automation"))
    theme["flags"] = {"hyde_enabled": True}
    monkeypatch.setattr(config_schema, "FEATURE_THEMES", [theme])

    # The config ASKS for it (evidence) and the effective config disagrees.
    effective = {"hyde_enabled": False}
    row = get_feature_themes(effective, {"hyde_enabled": True})[0]
    assert row["enabled"] is False
    assert [b["owner"] for b in row["blocked_by"]] == ["test_owner"], (
        "get_feature_themes did not surface an owner the registry returned — it is reading a "
        "hardcoded owner list again"
    )


def test_a_theme_reports_only_owners_that_actually_held_a_key(cfg_file):
    """No confident, actionable, wrong reasons. An owner is named only where the config ASKED
    for the flag and the effective config disagrees — never as a prediction about a flag
    nobody has turned on, because a probe can describe a path this surface does not take."""
    from config_schema import get_feature_themes

    # remote_enabled is off and unrequested; the security_policy probe claims the key, but
    # nothing has been held from anyone yet.
    row = next(t for t in get_feature_themes({"auto_tune_enabled": False}, {})
               if t["key"] == "remote_access")
    assert row["enabled"] is False
    assert row["blocked_by"] == []


def test_a_theme_whose_engine_is_not_installed_is_not_reported_enabled(cfg_file, monkeypatch):
    """GET /settings/themes reported advanced_search enabled:true on a box with no
    elasticsearch package — themes never consulted package presence, so it advertised a
    capability whose engine is absent."""
    import install.feature_status as fs
    from config_schema import get_feature_themes

    cfg = {"auto_tune_enabled": False, "hyde_enabled": True, "elasticsearch_enabled": True}

    monkeypatch.setattr(fs, "key_missing_packages",
                        lambda k: ["elasticsearch"] if k == "elasticsearch_enabled" else [])
    row = next(t for t in get_feature_themes(cfg) if t["key"] == "advanced_search")
    assert row["missing_packages"] == ["elasticsearch"]
    assert row["enabled"] is False, "a capability was advertised over a missing engine"

    monkeypatch.setattr(fs, "key_missing_packages", lambda k: [])
    row2 = next(t for t in get_feature_themes(cfg) if t["key"] == "advanced_search")
    assert row2["enabled"] is True


def test_theme_packages_are_derived_from_the_manifest_not_a_second_map():
    """The flag->package answer must come from FEATURE_MANIFEST, so adding a dep to a feature
    covers every flag it declares without a second list to forget."""
    from install.feature_status import key_missing_packages
    from install.setup_profiles import FEATURE_MANIFEST

    feat = next(f for f in FEATURE_MANIFEST if f["id"] == "search_elastic")
    assert "elasticsearch" in feat["deps"]
    # Whatever is installed on the runner, the answer must be a subset of the manifest's deps.
    assert set(key_missing_packages("elasticsearch_enabled")) <= set(feat["deps"])
    assert key_missing_packages("hyde_enabled") == [], "hyde declares no packages"


def test_post_themes_reports_the_effective_state_not_the_request(cfg_file, cpu_tier,
                                                                 monkeypatch):
    """C2's headline. POST /settings/themes returned {"ok":true,"enabled":true} for a flag
    that is NOT in force; the checkbox renders from the effective config, so it snapped back
    on reopen with a success toast still over it.

    THE OWNER CANNOT BE AUTO-TUNE HERE, and that is not a detail. `feature_theme_updates`
    deliberately adds any auto-tune-owned theme flag to `auto_tune_locked_keys`, precisely so
    the operator's choice survives the next load — so an auto-tune key can never demonstrate
    "asked for and not in force" through this endpoint. The maturity gate used to be the
    non-auto-tune owner; it is deleted, so a probe is injected into the real registry instead.
    Auto-tune still performs the actual revert (pinned CPU tier), the injected probe just claims
    the explanation — which also proves the lock remedy is scoped to auto-tune's OWN keys.
    """
    import config_schema
    import install.feature_status as fs

    def _fake_owner(key, cfg):
        return ("test_owner", "an injected registry probe claims this key") \
            if key == "hyde_enabled" else None

    monkeypatch.setattr(fs, "_KEY_OWNERS", [_fake_owner, *fs._KEY_OWNERS])

    theme = dict(next(t for t in config_schema.FEATURE_THEMES if t["key"] == "automation"))
    theme["flags"] = {"hyde_enabled": True}
    monkeypatch.setattr(config_schema, "FEATURE_THEMES", [theme])
    monkeypatch.setattr(config_schema, "_THEME_FLAG_WHITELIST", {"hyde_enabled"})

    d = _client().post("/settings/themes", json={"key": "automation", "enabled": True}).json()

    assert d["ok"] is True, "the write itself did happen"
    assert d["requested"] is True
    assert d["enabled"] is False, "the response claimed a capability that is not in force"
    assert d["in_force"] is False
    assert d["not_in_force"] == ["hyde_enabled"]
    row = next(r for r in d["report"] if r["key"] == "hyde_enabled")
    assert row["owner"] == "test_owner" and row["reason"], (
        "the response did not carry the owner the registry returned"
    )
    assert d["not_in_force_note"]


def test_an_unreadable_config_reports_unknown_not_all_clear(cfg_file):
    """UNKNOWN is not "all clear". If the file cannot be read we do not know what was asked
    for, so `in_force` is None and `ok` is False — never `in_force: True` beside `ok: False`,
    which is a cheerful answer assembled out of a failure. The panel keeps its last known set
    rather than clearing on this response."""
    from services.infrastructure.route_helpers import not_in_force_report

    cfg_file.write_text("{ NOT JSON", encoding="utf-8")
    import runtime_safety as rs

    rs.invalidate_config_cache()

    d = not_in_force_report()
    assert d["ok"] is False
    assert d["in_force"] is None, "an unreadable config reported as all-clear"
    assert d["error"]
