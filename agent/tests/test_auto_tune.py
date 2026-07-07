"""Hardware-adaptive optimization suite: tier classification + profile scaling.

Locks the guarantee that the same code produces a LEAN pipeline on weak hardware
(fast) and a RICH pipeline on strong/GPU hardware (max quality), and that a GPU is
only trusted when the llama build can actually offload to it.
"""
from __future__ import annotations

from services.infrastructure.auto_tune import (
    PROFILE_KEYS,
    apply_auto_tune,
    compute_optimization_profile,
    optimization_tier,
)

# Representative machines across the whole spectrum.
POTATO = {"cpu_physical": 4, "cpu_cores": 8, "ram_gb": 8.0, "vram_gb": 0.0, "acceleration_backend": "none", "machine_tier": "tier1"}
CPU_MID = {"cpu_physical": 6, "cpu_cores": 12, "ram_gb": 16.0, "vram_gb": 0.0, "acceleration_backend": "none", "machine_tier": "tier2"}
CPU_STRONG = {"cpu_physical": 16, "cpu_cores": 32, "ram_gb": 64.0, "vram_gb": 0.0, "acceleration_backend": "none", "machine_tier": "tier4"}
GPU_6GB = {"cpu_physical": 8, "cpu_cores": 16, "ram_gb": 16.0, "vram_gb": 6.0, "acceleration_backend": "cuda", "machine_tier": "tier2"}
GPU_12GB = {"cpu_physical": 8, "cpu_cores": 16, "ram_gb": 32.0, "vram_gb": 12.0, "acceleration_backend": "cuda", "machine_tier": "tier3"}
GPU_24GB = {"cpu_physical": 16, "cpu_cores": 32, "ram_gb": 64.0, "vram_gb": 24.0, "acceleration_backend": "cuda", "machine_tier": "tier4"}


def test_tier_classification_cpu():
    assert optimization_tier(POTATO, gpu_offload=False) == "potato"
    assert optimization_tier(CPU_MID, gpu_offload=False) == "cpu"
    assert optimization_tier(CPU_STRONG, gpu_offload=False) == "cpu_plus"


def test_tier_classification_gpu_requires_offload_build():
    # A real GPU only earns a GPU tier when the llama build can offload.
    assert optimization_tier(GPU_6GB, gpu_offload=True) == "gpu_low"
    assert optimization_tier(GPU_12GB, gpu_offload=True) == "gpu_mid"
    assert optimization_tier(GPU_24GB, gpu_offload=True) == "gpu_high"
    # Same GPU boxes on a CPU-only wheel fall back to CPU tiers (safe).
    assert optimization_tier(GPU_24GB, gpu_offload=False) in {"cpu", "cpu_plus"}
    assert optimization_tier(GPU_6GB, gpu_offload=False) in {"potato", "cpu"}


def test_cpu_build_never_offloads_layers():
    # Even with a 24GB GPU present, a CPU-only build must not set n_gpu_layers>0.
    prof = compute_optimization_profile(GPU_24GB, gpu_offload=False)
    assert prof["n_gpu_layers"] == 0
    assert prof["flash_attn"] is False


def test_gpu_build_offloads():
    prof = compute_optimization_profile(GPU_12GB, gpu_offload=True)
    assert prof["n_gpu_layers"] != 0  # -1 (all) or a positive count


def test_pipeline_weight_scales_up_monotonically():
    # The core promise: heavier hardware => bigger context, prompt budget, output.
    potato = compute_optimization_profile(POTATO, gpu_offload=False)
    strong = compute_optimization_profile(CPU_STRONG, gpu_offload=False)
    gpu = compute_optimization_profile(GPU_24GB, gpu_offload=True)

    assert potato["n_ctx"] < strong["n_ctx"] <= gpu["n_ctx"]
    assert potato["system_head_budget_ratio"] < gpu["system_head_budget_ratio"]
    assert potato["completion_max_tokens"] < gpu["completion_max_tokens"]
    assert potato["max_runtime_seconds"] < gpu["max_runtime_seconds"]


def test_potato_pipeline_is_lean():
    # Weak hardware skips the expensive extras (each is an extra LLM call / prefill cost).
    p = compute_optimization_profile(POTATO, gpu_offload=False)
    assert p["repo_cognition_inject_enabled"] is False
    assert p["hyde_enabled"] is False
    assert p["enable_self_reflection"] is False
    assert p["multi_agent_orchestration_enabled"] is False
    assert p["performance_mode"] == "low"


def test_gpu_pipeline_is_rich():
    p = compute_optimization_profile(GPU_24GB, gpu_offload=True)
    assert p["repo_cognition_inject_enabled"] is True
    assert p["hyde_enabled"] is True
    assert p["enable_self_reflection"] is True
    assert p["multi_agent_orchestration_enabled"] is True


def test_timeout_family_is_internally_consistent():
    # inner local <= outer llm <= run <= browser waits — so real work never false-times-out.
    for hw, off in [(POTATO, False), (CPU_STRONG, False), (GPU_24GB, True)]:
        p = compute_optimization_profile(hw, gpu_offload=off)
        run = p["max_runtime_seconds"]
        assert p["llm_local_timeout_seconds"] <= p["llm_timeout_seconds"]
        assert p["ui_agent_stream_timeout_seconds"] >= run
        assert p["ui_agent_json_timeout_seconds"] >= run


def test_apply_auto_tune_is_authoritative_but_respects_locks_and_optout():
    base = {"n_ctx": 999999, "hyde_enabled": True, "some_user_key": "keep"}

    # Off => untouched.
    off = apply_auto_tune({**base, "auto_tune_enabled": False})
    assert off["n_ctx"] == 999999

    # On => owned keys are overwritten, unrelated keys preserved.
    on = apply_auto_tune({**base, "auto_tune_enabled": True})
    assert on["n_ctx"] != 999999
    assert on["some_user_key"] == "keep"
    assert on.get("_auto_tune_tier")

    # Locked key keeps the user value even while auto-tune is on.
    locked = apply_auto_tune({**base, "auto_tune_enabled": True, "auto_tune_locked_keys": ["n_ctx"]})
    assert locked["n_ctx"] == 999999


def test_apply_auto_tune_only_touches_profile_keys():
    on = apply_auto_tune({"auto_tune_enabled": True, "unrelated": 1})
    changed = {k for k in on if k not in ("unrelated", "auto_tune_enabled", "_auto_tune_tier")}
    assert changed <= PROFILE_KEYS
