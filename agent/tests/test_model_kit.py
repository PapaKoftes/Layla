"""Tests for install.model_selector.recommend_kit — the hardware+domain+priority
aware "kit" recommender (Friend-Ready milestone, Track A).

Encodes the measured CPU reality: on a memory-bandwidth-bound CPU box a 7B-Q4 runs
~5 tok/s, so a 14B (~2 tok/s) is NOT a good experience even though it "fits". "Best
possible local coding" on CPU = the best *responsive* model, plus a same-family
speculative draft. Pure-stdlib over the bundled catalog; runs anywhere.
"""
import sys
from pathlib import Path

AGENT_DIR = Path(__file__).resolve().parent.parent
if str(AGENT_DIR) not in sys.path:
    sys.path.insert(0, str(AGENT_DIR))

from install.model_selector import _params_b, recommend_kit  # noqa: E402

# Hardware profiles
FRIEND_LAPTOP = {"ram_gb": 16.0, "vram_gb": 0.0, "acceleration_backend": "none",
                 "gpu_name": "none", "physical_cores": 4}
GPU_WORKSTATION = {"ram_gb": 32.0, "vram_gb": 24.0, "acceleration_backend": "cuda",
                   "gpu_name": "RTX 4090", "physical_cores": 16}
POTATO = {"ram_gb": 4.0, "vram_gb": 0.0, "acceleration_backend": "none",
          "gpu_name": "none", "physical_cores": 2}


def test_cpu_coding_quality_respects_usability_ceiling():
    """The key insight: on a 16GB CPU box, 'quality' must NOT pick the 14B that
    technically fits — it's too slow. It should land on the 7B."""
    kit = recommend_kit(FRIEND_LAPTOP, domain="coding", prefer="quality")
    assert kit is not None
    assert _params_b(kit["primary"]) <= 9.0, "must stay within the CPU usability ceiling"
    assert "7b" in kit["primary"]["name"].lower()
    assert kit["primary"]["category"] == "coding"


def test_cpu_coding_pairs_same_family_speculative_draft():
    """A >=7B CPU primary should pair a tiny SAME-FAMILY draft (safe tokenizer)."""
    kit = recommend_kit(FRIEND_LAPTOP, domain="coding", prefer="quality")
    draft = kit["draft"]
    assert draft is not None, "expected a speculative draft for the 7B coder"
    assert draft["family"] == kit["primary"]["family"], "draft must be same family (tokenizer-safe)"
    assert _params_b(draft) <= 1.5
    assert kit["settings"]["speculative_draft"] == draft["filename"]


def test_gpu_unlocks_larger_models():
    """With a real GPU, 'quality' may exceed the CPU ceiling (bigger model is fine)."""
    cpu = recommend_kit(FRIEND_LAPTOP, domain="coding", prefer="quality")
    gpu = recommend_kit(GPU_WORKSTATION, domain="coding", prefer="quality")
    assert gpu is not None
    assert _params_b(gpu["primary"]) > _params_b(cpu["primary"]), "GPU should allow a bigger coder"


def test_speed_prefers_smaller_or_equal_than_quality():
    """On the same hardware, 'speed' must never pick a larger model than 'quality'."""
    q = recommend_kit(GPU_WORKSTATION, domain="coding", prefer="quality")
    s = recommend_kit(GPU_WORKSTATION, domain="coding", prefer="speed")
    assert _params_b(s["primary"]) <= _params_b(q["primary"])
    # speed should not attach a draft (it adds orchestration overhead for little gain)
    assert s["draft"] is None


def test_domain_maps_to_affinity_aspect():
    """A coding (qwen) kit should resolve to a personality via _recommended_aspects."""
    kit = recommend_kit(FRIEND_LAPTOP, domain="coding", prefer="balanced")
    assert kit["aspect"], "kit should carry a domain personality (aspect)"


def test_settings_reflect_cpu_vs_gpu():
    cpu = recommend_kit(FRIEND_LAPTOP, domain="coding", prefer="balanced")
    gpu = recommend_kit(GPU_WORKSTATION, domain="coding", prefer="balanced")
    assert cpu["settings"]["n_gpu_layers"] == 0
    assert gpu["settings"]["n_gpu_layers"] == -1
    assert cpu["settings"]["n_threads"] == 4


def test_potato_degrades_gracefully():
    """A 4GB box can't fit a 7B coder; it must still return *something*, not crash."""
    kit = recommend_kit(POTATO, domain="coding", prefer="balanced")
    assert kit is not None
    assert kit["primary"] is not None


def test_rationale_is_human_readable():
    kit = recommend_kit(FRIEND_LAPTOP, domain="coding", prefer="quality")
    assert "CPU-only" in kit["rationale"]
    assert "tok/s" in kit["rationale"]


if __name__ == "__main__":
    import pytest
    sys.exit(pytest.main([__file__, "-v"]))
