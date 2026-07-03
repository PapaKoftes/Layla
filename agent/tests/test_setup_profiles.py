"""Tests for the Setup & Profiles resolution (install/setup_profiles.py) — pure, no app/model."""
from __future__ import annotations

from install.setup_profiles import (
    FEATURE_MANIFEST,
    PROFILES,
    apply_setup,
    feature_by_id,
    features_to_install,
    profile_by_id,
    resolve_setup_config,
)


def test_every_profile_references_valid_features():
    for p in PROFILES:
        for fid in p["features"]:
            assert feature_by_id(fid) is not None, f"{p['id']} references unknown feature {fid}"


def test_every_feature_has_required_keys():
    for f in FEATURE_MANIFEST:
        for k in ("id", "label", "flags", "deps", "models", "size_mb", "unlocks"):
            assert k in f, f"{f.get('id')} missing {k}"
    ids = [f["id"] for f in FEATURE_MANIFEST]
    assert len(ids) == len(set(ids)), "duplicate feature ids"


def test_minimal_profile_is_lean():
    cfg = resolve_setup_config(["minimal"])
    assert cfg["setup_features"] == []
    assert cfg.get("performance_mode") == "potato"
    assert cfg.get("mcp_client_enabled") is None  # no optional features enabled
    assert cfg["enabled_aspects"] == ["morrigan"]


def test_coding_profile_enables_mcp_and_tool_first():
    cfg = resolve_setup_config(["coding"])
    assert cfg.get("mcp_client_enabled") is True
    assert cfg.get("tool_first_enforcement_enabled") is True
    assert "mcp" in cfg["setup_features"]


def test_power_profile_enables_all_features():
    cfg = resolve_setup_config(["power"])
    assert set(cfg["setup_features"]) == {f["id"] for f in FEATURE_MANIFEST}
    assert cfg.get("voice_stt_prewarm_enabled") is True
    assert cfg.get("encryption_at_rest_enabled") is True


def test_explicit_features_union_with_profile():
    cfg = resolve_setup_config(["minimal"], ["voice", "encryption"])
    assert cfg.get("voice_tts_prewarm_enabled") is True
    assert cfg.get("encryption_at_rest_enabled") is True
    assert set(["voice", "encryption"]).issubset(set(cfg["setup_features"]))


def test_multi_profile_unions_features_and_aspects():
    cfg = resolve_setup_config(["companion", "coding"])
    assert "initiative" in cfg["setup_features"] and "mcp" in cfg["setup_features"]
    assert cfg["enabled_aspects"][0] == "morrigan"  # union preserves order + dedups
    assert len(cfg["enabled_aspects"]) == len(set(cfg["enabled_aspects"]))


def test_features_to_install_only_returns_installable():
    inst = features_to_install(["mcp", "voice", "hyde"])
    ids = {f["id"] for f in inst}
    assert "voice" in ids  # has deps + models
    assert "mcp" not in ids and "hyde" not in ids  # no deps/models → nothing to install


def test_unknown_profile_ignored():
    cfg = resolve_setup_config(["nonsense"])
    assert cfg["setup_profiles"] == []


def test_apply_setup_merges_onto_current_without_saving():
    current = {"model_filename": "x.gguf", "mcp_client_enabled": False, "keep_me": 1}
    merged = apply_setup(["coding"], ["encryption"], current_cfg=current, save=False)
    assert merged["keep_me"] == 1                       # untouched key preserved
    assert merged["model_filename"] == "x.gguf"          # untouched key preserved
    assert merged["mcp_client_enabled"] is True          # overridden by coding profile
    assert merged["encryption_at_rest_enabled"] is True  # explicit feature
    assert merged["setup_profiles"] == ["coding"]
