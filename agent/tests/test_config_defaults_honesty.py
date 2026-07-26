"""The displayed default must equal the effective default — and a feature ships OFF only when off
is NECESSITATED.

WHY THIS FILE EXISTS. config_schema.EDITABLE_SCHEMA advertises a `default` for every editable
setting (the value the /settings UI shows and coerce_and_clamp falls back to), while
runtime_safety.load_config() decides the value that actually reaches the model. When the two
disagree, the control lies: it shows one default and applies another. This was real —

  * enable_self_reflection            schema False  / runtime True
  * deterministic_tool_routes_enabled schema False  / runtime True
  * max_tool_calls                    schema 5      / runtime 20

— and every one of those is a green "saved" over a value the operator never sees.

The parity test below enumerates EVERY editable boolean/number and asserts schema == runtime on an
empty config, excluding only the keys hardware auto-tune legitimately overwrites per tier (those
are dynamic by design and marked auto_tune_owned in the schema). The remaining tests pin the rest
of the cluster: the two features flipped ON because they are cheap + safe + dependency-free
(item 7), the two reachability gaps now settable (item 8), and the genuinely-necessitated OFF
defaults that must STAY off and say WHY (item 9), so a future blanket flip-on trips a red gate.
"""
from __future__ import annotations

import pytest

import config_schema as cs
import runtime_safety as rs
from services.infrastructure.auto_tune import PROFILE_KEYS

_MISSING = object()
_SCHEMA_BY_KEY = {e["key"]: e for e in cs.EDITABLE_SCHEMA}


@pytest.fixture()
def empty_cfg(tmp_path, monkeypatch):
    """Point runtime_safety at a throwaway EMPTY config so we read shipped defaults, never
    operator state. Non-auto-tune keys are hardware-independent, so this is deterministic on CI."""
    p = tmp_path / "runtime_config.json"
    p.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(rs, "CONFIG_FILE", p)
    rs.invalidate_config_cache()
    yield p
    rs.invalidate_config_cache()


def _editable_bool_number_with_default():
    for e in cs.EDITABLE_SCHEMA:
        if e.get("type") in ("boolean", "number") and "default" in e:
            yield e


# ── (a) THE PARITY SCAN — every editable bool/number, schema default == runtime default ─────────
def test_schema_default_equals_runtime_default_for_every_editable_bool_and_number(empty_cfg):
    """The headline invariant. Auto-tune-owned keys (PROFILE_KEYS ∩ editable) are excluded: they
    are overwritten per hardware tier at every load_config(), so their effective value is
    legitimately dynamic and the schema marks them auto_tune_owned. Everything else must match."""
    eff = rs.load_config()

    lies: list[tuple[str, object, object]] = []
    checked = 0
    for e in _editable_bool_number_with_default():
        key = e["key"]
        if key in PROFILE_KEYS:
            continue  # dynamic by design — see test_settings_honesty.py for the auto-tune contract
        sd = e["default"]
        rv = eff.get(key, _MISSING)
        checked += 1
        if rv is _MISSING:
            lies.append((key, sd, "<ABSENT from load_config>"))
        elif rv != sd:
            lies.append((key, sd, rv))

    assert not lies, (
        "the /settings schema advertises a default the runtime does not apply — a control that "
        "shows one value and honours another:\n"
        + "\n".join(f"  {k}: schema default={sd!r} but load_config()={rv!r}" for k, sd, rv in lies)
        + "\n\nReconcile in config_schema.EDITABLE_SCHEMA or runtime_safety.load_config so the "
        "displayed default equals the effective default."
    )
    assert checked >= 20, f"the parity scan only saw {checked} keys — it is not actually running"


# ── (a′) THE TWO NAMED OFFENDERS (+ the one the scan surfaced) ARE RECONCILED ────────────────────
def test_item6_known_offenders_are_reconciled(empty_cfg):
    eff = rs.load_config()

    # deterministic_tool_routes_enabled: was schema False / runtime True. NOT auto-tune managed, so
    # the schema must now equal the live runtime value.
    assert _SCHEMA_BY_KEY["deterministic_tool_routes_enabled"]["default"] is True
    assert eff.get("deterministic_tool_routes_enabled") is True

    # max_tool_calls: was schema 5 / runtime 20 (the example config already shipped 20).
    assert _SCHEMA_BY_KEY["max_tool_calls"]["default"] == 20
    assert eff.get("max_tool_calls") == 20

    # enable_self_reflection: was schema False / static-runtime True. It IS auto-tune managed (a
    # PROFILE_KEY), so auto-tune legitimately reverts it on the weakest tier and load_config's value
    # is tier-dependent — the reconciliation is at the BASELINE: the schema now advertises the True
    # static default the loader ships, instead of a False the loader never used.
    assert "enable_self_reflection" in PROFILE_KEYS
    assert _SCHEMA_BY_KEY["enable_self_reflection"]["default"] is True


def test_enable_self_reflection_baseline_matches_schema_with_auto_tune_off(tmp_path, monkeypatch):
    """The tier-independent proof for the auto-tune-managed offender: with auto-tune OFF, the
    loader's static default must equal the schema's displayed default."""
    p = tmp_path / "runtime_config.json"
    p.write_text('{"auto_tune_enabled": false}', encoding="utf-8")
    monkeypatch.setattr(rs, "CONFIG_FILE", p)
    rs.invalidate_config_cache()
    try:
        eff = rs.load_config()
    finally:
        rs.invalidate_config_cache()
    assert eff.get("enable_self_reflection") is True
    assert _SCHEMA_BY_KEY["enable_self_reflection"]["default"] is True


# ── (d) ITEM 7 — the two cheap/safe/dependency-free features flipped ON by default ───────────────
def test_item7_flipped_keys_are_true_by_default(empty_cfg):
    eff = rs.load_config()
    assert eff.get("inline_initiative_enabled") is True, "inline initiative must ship ON"
    assert eff.get("grounding_enabled") is True, "RAG grounding must ship ON"
    assert eff.get("grounding_mode") == "flag", "grounding must ship in the non-invasive flag mode"
    # inline_initiative_enabled is also a schema key: its displayed default must mirror the flip.
    assert _SCHEMA_BY_KEY["inline_initiative_enabled"]["default"] is True


def test_item7_engines_import_cleanly():
    """Both engines are in-repo and model-free. This is a config/import-level smoke test only —
    a LIVE-model turn is needed to confirm they actually fire end to end (the unit suite mocks
    the model)."""
    from services.infrastructure import initiative_inline
    from services.retrieval import grounding

    assert hasattr(initiative_inline, "maybe_append_inline_suggestion")
    # grounding runs its model-free lexical scorer with no LLM and no network.
    out = grounding.check_grounding(
        "Paris is the capital of France.",
        ["France's capital is Paris, a large city in Europe."],
        {"grounding_enabled": True, "grounding_mode": "flag"},
    )
    assert out["enabled"] is True


# ── (c) ITEM 8 — the reachability gaps are now settable AND clamped ──────────────────────────────
def test_item8_new_keys_are_editable():
    keys = cs.get_editable_keys()
    assert "self_consistency_samples" in keys, "self_consistency_samples must be a settable key"
    assert "german_mode_enabled" in keys, "german_mode_enabled must be a settable key"


def test_item8_self_consistency_samples_is_clamped_1_to_7():
    entry = _SCHEMA_BY_KEY["self_consistency_samples"]
    assert entry["type"] == "number"
    assert entry["default"] == 1
    assert entry["min"] == 1 and entry["max"] == 7, "a potato box must not be told to sample huge"
    # coerce_and_clamp enforces the range on both the write and the load path.
    assert cs.coerce_and_clamp("self_consistency_samples", 99) == 7
    assert cs.coerce_and_clamp("self_consistency_samples", 0) == 1
    assert cs.coerce_and_clamp("self_consistency_samples", 4) == 4
    assert cs.coerce_and_clamp("self_consistency_samples", "bad") == 1  # -> schema default


def test_item8_german_mode_is_a_plain_off_boolean():
    entry = _SCHEMA_BY_KEY["german_mode_enabled"]
    assert entry["type"] == "boolean"
    assert entry["default"] is False  # language-specific; not a necessitated-danger off
    assert cs.coerce_and_clamp("german_mode_enabled", "true") is True


# ── (b) ITEM 9 — the necessitated-OFF keys STAY off and NAME why ─────────────────────────────────
# A feature ships OFF only for a real reason: a security risk, a heavy cost on the weakest tier, or
# a missing dependency/credential. Each key here must default False AND its hint must name that
# class, so a future blanket flip-on has to argue with a red test.
NECESSITATED_OFF = (
    "plugins_enabled",
    "skill_venv_enabled",
    "skill_packs_execute_enabled",
    "mcp_client_enabled",
    "autonomous_mode",
    "autonomy_optimizer_enabled",
    "tool_approval_bypass",
    "remote_enabled",
    "allow_legacy_remote_api_key",
    "admin_mode",
    "admin_blocklist_override",
)

# Tokens that name one of the three necessitating classes (security / potato-perf /
# needs-dep-or-credential). A hint must contain at least one.
_CLASS_TOKENS = (
    "security", "dangerous", "powerful", "trust", "privilege",   # security
    "potato", "perf", "expensive", "cpu",                        # potato-perf
    "credential", "auth", "dependenc", "server", "supply-chain", "subprocess",  # needs-dep/cred
)


def test_necessitated_off_keys_default_false_in_the_schema():
    for key in NECESSITATED_OFF:
        entry = _SCHEMA_BY_KEY.get(key)
        assert entry is not None, f"'{key}' vanished from EDITABLE_SCHEMA"
        assert entry.get("default") is False, (
            f"'{key}' must ship OFF — it is a genuinely-necessitated off default. If you meant to "
            "flip it on, that needs its own justified change, not a blanket default sweep."
        )


def test_necessitated_off_keys_default_false_in_the_runtime(empty_cfg):
    """The lock has teeth only if the RUNTIME agrees — otherwise the schema could say False while
    load_config quietly ships True (the exact item-6 defect, in reverse)."""
    eff = rs.load_config()
    for key in NECESSITATED_OFF:
        assert eff.get(key) is False, (
            f"'{key}' is {eff.get(key)!r} at the runtime layer. A dangerous capability that ships "
            "on is the outcome this lock exists to prevent."
        )


def test_necessitated_off_keys_name_their_reason():
    for key in NECESSITATED_OFF:
        hint = (_SCHEMA_BY_KEY[key].get("hint") or "").lower()
        assert any(tok in hint for tok in _CLASS_TOKENS), (
            f"'{key}' ships OFF but its hint never says WHY (security / potato-perf / "
            f"needs-dep-or-credential):\n  {_SCHEMA_BY_KEY[key].get('hint')!r}"
        )


# ── ITEM 5 — deliberation_mode default is explicitly 'auto', schema and runtime agree ────────────
def test_deliberation_mode_default_is_auto_and_consistent(empty_cfg):
    assert _SCHEMA_BY_KEY["deliberation_mode"]["default"] == "auto"
    assert rs.load_config().get("deliberation_mode") == "auto"
    # And the six-aspect debate itself is NOT forced on — text-only + slow on a 3B.
    assert _SCHEMA_BY_KEY["deliberation_enabled"]["default"] is False
    assert rs.load_config().get("deliberation_enabled") is False


# ── ITEM 35 — HyDE honesty: off by default AND the auto-tune caveat/lock remedy is present ───────
def test_hyde_stays_off_and_hint_states_the_auto_tune_caveat():
    entry = _SCHEMA_BY_KEY["hyde_enabled"]
    assert entry["default"] is False, "HyDE must NOT be on by default (expensive extra call)"
    hint = entry["hint"].lower()
    assert "auto-tune" in hint or "auto_tune" in hint, "hint must state the auto-tune caveat"
    assert "auto_tune_locked_keys" in entry["hint"], "hint must name the lock remedy"


if __name__ == "__main__":
    import sys

    sys.exit(pytest.main([__file__, "-v"]))
