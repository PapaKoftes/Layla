"""BL-107 / REQ-22: release-gate determinism forces greedy decoding when enabled."""
from __future__ import annotations

from services.llm.inference_router import apply_decoding_determinism


def test_default_leaves_sampling_untouched():
    # Off (or missing flag) → params pass through unchanged.
    assert apply_decoding_determinism({}, 0.7, 0.95, 40) == (0.7, 0.95, 40)
    assert apply_decoding_determinism(None, 0.7, 0.95, 40) == (0.7, 0.95, 40)
    assert apply_decoding_determinism({"deterministic_decoding_enabled": False}, 0.7, 0.9, 40) == (0.7, 0.9, 40)


def test_enabled_forces_greedy():
    t, p, k = apply_decoding_determinism({"deterministic_decoding_enabled": True}, 0.7, 0.95, 40)
    assert t == 0.0 and k == 1 and p == 1.0        # greedy → reproducible, no sampling randomness


def test_builtin_config_has_flag_off_by_default():
    import tempfile
    import uuid
    from pathlib import Path

    import runtime_safety

    fake = Path(tempfile.gettempdir()) / f"det_cfg_{uuid.uuid4().hex}.json"
    import pytest
    mp = pytest.MonkeyPatch()
    mp.setattr(runtime_safety, "CONFIG_FILE", fake)
    mp.setattr(runtime_safety, "_config_cache", None)
    mp.setattr(runtime_safety, "_config_last_check", 0.0)
    try:
        cfg = runtime_safety.load_config()
        assert cfg.get("deterministic_decoding_enabled") is False
    finally:
        mp.undo()
