"""B2 release-blocker: settings/config values are coerced, clamped, and written atomically.

A user (via the Settings UI/API) or a hand-edited runtime_config.json must never be able
to push an out-of-range / garbage value into the llama.cpp layer, and a crash mid-write must
never truncate the config.
"""
from __future__ import annotations

import json
from unittest.mock import patch

import config_schema as cs
import runtime_safety as rs


# ── coerce_and_clamp (single source of truth) ────────────────────────────────
def test_clamp_out_of_range_numbers():
    assert cs.coerce_and_clamp("temperature", 50) == 1.5      # max 1.5
    assert cs.coerce_and_clamp("temperature", -5) == 0.01     # min 0.01
    assert cs.coerce_and_clamp("n_gpu_layers", -999) == -1    # min -1
    assert cs.coerce_and_clamp("n_gpu_layers", 500) == 99     # max 99
    assert cs.coerce_and_clamp("n_ctx", 1) == 256             # min 256
    assert cs.coerce_and_clamp("top_p", 5) == 1               # max 1


def test_clamp_preserves_int_vs_float():
    assert isinstance(cs.coerce_and_clamp("n_ctx", 8192), int)
    assert cs.coerce_and_clamp("n_ctx", 8192) == 8192
    assert isinstance(cs.coerce_and_clamp("temperature", 0.7), float)
    assert cs.coerce_and_clamp("temperature", 0.7) == 0.7


def test_unparseable_number_falls_back_to_default():
    assert cs.coerce_and_clamp("n_ctx", "abc") == 4096        # schema default
    assert cs.coerce_and_clamp("temperature", None) == 0.2


def test_boolean_normalisation_and_unknown_passthrough():
    assert cs.coerce_and_clamp("uncensored", "true") is True
    assert cs.coerce_and_clamp("uncensored", "0") is False
    assert cs.coerce_and_clamp("uncensored", True) is True
    assert cs.coerce_and_clamp("not_a_schema_key", {"x": 1}) == {"x": 1}


# ── save_config_keys: race-safe, atomic, clamped write ───────────────────────
def test_save_config_keys_clamps_and_persists(tmp_path):
    cfgfile = tmp_path / "runtime_config.json"
    with patch.object(rs, "CONFIG_FILE", cfgfile):
        saved = rs.save_config_keys({"temperature": 99, "n_ctx": 1, "not_editable_xyz": 1}, editable_only=True, clamp=True)
        assert set(saved) == {"temperature", "n_ctx"}          # non-editable dropped
        on_disk = json.loads(cfgfile.read_text(encoding="utf-8"))
        assert on_disk["temperature"] == 1.5                    # clamped
        assert on_disk["n_ctx"] == 256                          # clamped
        assert "not_editable_xyz" not in on_disk
        assert not (tmp_path / "runtime_config.json.tmp").exists()  # no leftover temp


def test_save_config_keys_merges_not_clobbers(tmp_path):
    cfgfile = tmp_path / "runtime_config.json"
    cfgfile.write_text(json.dumps({"temperature": 0.3, "top_k": 40}), encoding="utf-8")
    with patch.object(rs, "CONFIG_FILE", cfgfile):
        rs.save_config_keys({"top_k": 50}, editable_only=True, clamp=True)
        on_disk = json.loads(cfgfile.read_text(encoding="utf-8"))
        assert on_disk["temperature"] == 0.3                    # untouched key preserved
        assert on_disk["top_k"] == 50


def test_atomic_write_config_is_atomic(tmp_path):
    cfgfile = tmp_path / "runtime_config.json"
    with patch.object(rs, "CONFIG_FILE", cfgfile):
        rs.atomic_write_config({"model_filename": "x.gguf", "n_ctx": 4096})
        assert json.loads(cfgfile.read_text(encoding="utf-8"))["model_filename"] == "x.gguf"
        assert not (tmp_path / "runtime_config.json.tmp").exists()


def test_appearance_keys_write_without_clamp(tmp_path):
    cfgfile = tmp_path / "runtime_config.json"
    with patch.object(rs, "CONFIG_FILE", cfgfile):
        saved = rs.save_config_keys({"ui_avatar_seed": "abc123"}, editable_only=False, clamp=False)
        assert saved == ["ui_avatar_seed"]
        assert json.loads(cfgfile.read_text(encoding="utf-8"))["ui_avatar_seed"] == "abc123"


# ── load_config clamps a hand-edited garbage file ────────────────────────────
def test_load_config_clamps_hand_edited_garbage(tmp_path):
    cfgfile = tmp_path / "runtime_config.json"
    cfgfile.write_text(json.dumps({"temperature": 999, "n_gpu_layers": -999, "sandbox_root": str(tmp_path / "sb")}), encoding="utf-8")
    with patch.object(rs, "CONFIG_FILE", cfgfile):
        rs.invalidate_config_cache()
        cfg = rs.load_config()
        rs.invalidate_config_cache()
        assert cfg["temperature"] == 1.5
        assert cfg["n_gpu_layers"] == -1
