"""
Hardware-adaptive optimization suite.

Detects the machine's capability tier and produces a COMPLETE optimization
profile so Layla runs at the best quality-vs-speed balance on ANY hardware —
from a GPU-less 4-core laptop to a multi-GPU workstation — with zero hand-tuning.

Two axes are tuned together (this is the important part):

  1. INFERENCE params (delegated to hardware_detect.get_recommended_settings):
     n_threads (physical cores), n_gpu_layers, n_ctx, n_batch, flash_attn, …

  2. PIPELINE WEIGHT (new here): how much work the agent does per turn — system-
     prompt budget, repo/project context injection, HyDE/self-reflection/multi-
     agent extra LLM calls, reasoning depth, output tokens, runtime caps. On a
     slow CPU the *prompt prefill* and *extra model calls* dominate latency, so
     weak tiers get a LEAN pipeline (fast) while GPU tiers get the RICH pipeline
     (max quality). Same code, hardware-appropriate behaviour.

Applied authoritatively at config-load (auto_tune_enabled, default on) so the
running config always reflects the optimal profile for the detected hardware.
Users can opt out entirely (auto_tune_enabled=false) or lock individual keys
(auto_tune_locked_keys=[...]).
"""
from __future__ import annotations

from services.infrastructure.hardware_detect import detect_hardware, get_recommended_settings


def _gpu_offload_available() -> bool:
    """True only if a GPU is present AND the installed llama-cpp build can offload to it.

    Detecting a GPU is not enough: the prebuilt CPU wheel cannot offload, so setting
    n_gpu_layers>0 there would crash the load. This gates the GPU tiers on real capability,
    so a GPU box running a CPU-only build is (correctly, safely) treated as a CPU box until
    the GPU build is installed.
    """
    try:
        import llama_cpp
        fn = getattr(llama_cpp, "llama_supports_gpu_offload", None)
        return bool(fn()) if callable(fn) else False
    except Exception:
        return False

# Keys the suite owns. A user value only wins if the key is listed in
# `auto_tune_locked_keys` (or auto_tune is disabled). Everything else is derived.
PROFILE_KEYS = {
    # inference (from hardware_detect.get_recommended_settings)
    "n_ctx", "n_batch", "n_threads", "n_threads_batch", "n_gpu_layers",
    "flash_attn", "speculative_decoding_enabled",
    "context_aggressive_compress_enabled", "context_auto_compact_ratio",
    # pipeline weight (from _PIPELINE below)
    "performance_mode", "system_head_budget_ratio",
    "repo_cognition_inject_enabled", "repo_cognition_max_chars",
    "project_memory_inject_max_chars", "hyde_enabled",
    "enable_self_reflection", "multi_agent_orchestration_enabled",
    "output_quality_gate_enabled", "completion_max_tokens",
    "max_runtime_seconds", "chat_light_max_runtime_seconds",
    "llm_timeout_seconds", "llm_local_timeout_seconds",
    "tool_call_timeout_seconds", "ui_agent_stream_timeout_seconds",
    "ui_agent_json_timeout_seconds",
}


def optimization_tier(hw: dict | None = None, gpu_offload: bool | None = None) -> str:
    """Finer capability tier than machine_tier — the axis the profile keys off.

    potato   : CPU-only, <=4 physical cores OR <12GB RAM  (lean everything)
    cpu      : CPU-only, mid (<=8 cores / <24GB RAM)
    cpu_plus : CPU-only, strong (8+ cores, 24GB+ RAM — can run a 7B)
    gpu_low  : any GPU, <8GB VRAM (partial offload)
    gpu_mid  : GPU 8-16GB VRAM (full offload, 7-14B)
    gpu_high : GPU 16GB+ VRAM (14-32B, max quality)

    A GPU only counts if the installed llama build can actually offload to it
    (`gpu_offload`); a GPU box on a CPU-only wheel is treated as CPU until the
    GPU build is installed. Pass gpu_offload explicitly to simulate either build.
    """
    h = hw if hw is not None else detect_hardware()
    if gpu_offload is None:
        gpu_offload = _gpu_offload_available()
    vram = float(h.get("vram_gb") or 0.0)
    accel = str(h.get("acceleration_backend") or "none")
    ram = float(h.get("ram_gb") or 8.0)
    phys = int(h.get("cpu_physical") or h.get("cpu_cores") or 4)
    has_gpu = accel != "none" and vram >= 2.0 and bool(gpu_offload)

    if has_gpu:
        if vram >= 16:
            return "gpu_high"
        if vram >= 8:
            return "gpu_mid"
        return "gpu_low"
    # CPU-only
    if phys <= 4 or ram < 12:
        return "potato"
    if phys <= 8 or ram < 24:
        return "cpu"
    return "cpu_plus"


# Pipeline-weight profile per tier. The guiding rule: on hardware where a model
# call is cheap (GPU), do MORE per turn (bigger prompt, richer context, extra
# verification/reflection calls, deeper reasoning). On hardware where a call is
# expensive (CPU), do LESS (small prompt = fast prefill, no extra calls) so the
# single answer comes back quickly. All keys are real, config-schema keys.
_PIPELINE: dict[str, dict] = {
    "potato": {
        "performance_mode": "low",
        "system_head_budget_ratio": 0.22,       # small system prompt => fast CPU prefill
        "repo_cognition_inject_enabled": False,  # ~6k-char inject is pure prefill cost here
        "repo_cognition_max_chars": 1500,
        "project_memory_inject_max_chars": 700,
        "hyde_enabled": False,                   # skips an extra retrieval LLM call
        "enable_self_reflection": False,         # skips an extra LLM call
        "multi_agent_orchestration_enabled": False,
        "output_quality_gate_enabled": False,
        "completion_max_tokens": 256,
        "context_auto_compact_ratio": 0.6,
        "max_runtime_seconds": 300,
        "chat_light_max_runtime_seconds": 60,
    },
    "cpu": {
        "performance_mode": "low",
        "system_head_budget_ratio": 0.28,
        "repo_cognition_inject_enabled": True,
        "repo_cognition_max_chars": 2500,
        "project_memory_inject_max_chars": 1500,
        "hyde_enabled": False,
        "enable_self_reflection": False,
        "multi_agent_orchestration_enabled": False,
        "output_quality_gate_enabled": True,
        "completion_max_tokens": 384,
        "context_auto_compact_ratio": 0.65,
        "max_runtime_seconds": 600,
        "chat_light_max_runtime_seconds": 75,
    },
    "cpu_plus": {
        "performance_mode": "auto",
        "system_head_budget_ratio": 0.33,
        "repo_cognition_inject_enabled": True,
        "repo_cognition_max_chars": 4000,
        "project_memory_inject_max_chars": 3000,
        "hyde_enabled": False,
        "enable_self_reflection": True,
        "multi_agent_orchestration_enabled": False,
        "output_quality_gate_enabled": True,
        "completion_max_tokens": 512,
        "context_auto_compact_ratio": 0.7,
        "max_runtime_seconds": 900,
        "chat_light_max_runtime_seconds": 90,
    },
    "gpu_low": {
        "performance_mode": "auto",
        "system_head_budget_ratio": 0.38,
        "repo_cognition_inject_enabled": True,
        "repo_cognition_max_chars": 6000,
        "project_memory_inject_max_chars": 4000,
        "hyde_enabled": True,
        "enable_self_reflection": True,
        "multi_agent_orchestration_enabled": False,
        "output_quality_gate_enabled": True,
        "completion_max_tokens": 512,
        "context_auto_compact_ratio": 0.75,
        "max_runtime_seconds": 900,
        "chat_light_max_runtime_seconds": 90,
    },
    "gpu_mid": {
        "performance_mode": "high",
        "system_head_budget_ratio": 0.4,
        "repo_cognition_inject_enabled": True,
        "repo_cognition_max_chars": 8000,
        "project_memory_inject_max_chars": 5000,
        "hyde_enabled": True,
        "enable_self_reflection": True,
        "multi_agent_orchestration_enabled": True,
        "output_quality_gate_enabled": True,
        "completion_max_tokens": 768,
        "context_auto_compact_ratio": 0.8,
        "max_runtime_seconds": 1200,
        "chat_light_max_runtime_seconds": 120,
    },
    "gpu_high": {
        "performance_mode": "high",
        "system_head_budget_ratio": 0.45,
        "repo_cognition_inject_enabled": True,
        "repo_cognition_max_chars": 12000,
        "project_memory_inject_max_chars": 8000,
        "hyde_enabled": True,
        "enable_self_reflection": True,
        "multi_agent_orchestration_enabled": True,
        "output_quality_gate_enabled": True,
        "completion_max_tokens": 1024,
        "context_auto_compact_ratio": 0.85,
        "max_runtime_seconds": 1800,
        "chat_light_max_runtime_seconds": 150,
    },
}


def compute_optimization_profile(hw: dict | None = None, gpu_offload: bool | None = None) -> dict:
    """Return the complete optimization profile (inference + pipeline) for `hw`."""
    h = hw if hw is not None else detect_hardware()
    if gpu_offload is None:
        gpu_offload = _gpu_offload_available()
    tier = optimization_tier(h, gpu_offload)

    profile: dict = dict(get_recommended_settings(h))  # inference params (physical threads, gpu layers, ctx, batch, flash)
    profile.update(_PIPELINE[tier])                    # pipeline weight

    # Safety: never ask a CPU-only llama build to offload layers — it would fail the load.
    # (optimization_tier already treats such a box as a CPU tier; this hard-guards the param.)
    if not gpu_offload:
        profile["n_gpu_layers"] = 0
        profile["flash_attn"] = False

    # n_ctx/n_batch by the FINER tier: get_recommended_settings sizes context off RAM, but on a
    # CPU box prefill speed is bound by cores — a 4-core box wants a SMALL context (fast prefill)
    # even with 16GB RAM, while a GPU box wants a big one. system_head_budget_ratio × n_ctx is the
    # system-prompt size, so this is the single biggest speed/quality lever.
    _CTX = {"potato": 2048, "cpu": 2048, "cpu_plus": 4096, "gpu_low": 8192, "gpu_mid": 8192, "gpu_high": 16384}
    _BATCH = {"potato": 512, "cpu": 512, "cpu_plus": 512, "gpu_low": 512, "gpu_mid": 1024, "gpu_high": 1024}
    profile["n_ctx"] = _CTX[tier]
    profile["n_batch"] = _BATCH[tier]

    # Keep the timeout family internally consistent so real work never gets a
    # false "timed out": inner local <= outer llm <= run <= browser waits.
    run = int(profile.get("max_runtime_seconds", 900))
    llm = max(180, min(run, 300))
    profile["llm_local_timeout_seconds"] = llm
    profile["llm_timeout_seconds"] = llm
    profile["tool_call_timeout_seconds"] = max(120, min(run, 300))
    profile["ui_agent_stream_timeout_seconds"] = run + 60
    profile["ui_agent_json_timeout_seconds"] = run + 60

    profile["_opt_tier"] = tier
    return profile


def apply_auto_tune(cfg: dict) -> dict:
    """Overlay the hardware-optimal profile onto `cfg`, AUTHORITATIVELY.

    Unlike hardware_detect.apply_to_config (which only fills gaps), this makes
    auto-tune win for the keys it owns — because a stale hand-set value is
    exactly how a machine ends up mis-optimized. Escape hatches:
      • auto_tune_enabled = false        → do nothing (fully manual).
      • auto_tune_locked_keys = [...]     → keep the user's value for those keys.
    Returns a new dict; never mutates `cfg`.
    """
    try:
        if not cfg.get("auto_tune_enabled", True):
            return cfg
        profile = compute_optimization_profile()
        locked = set(cfg.get("auto_tune_locked_keys") or [])
        merged = dict(cfg)
        for k, v in profile.items():
            if k == "_opt_tier":
                continue
            if k in PROFILE_KEYS and k not in locked:
                merged[k] = v
        merged["_auto_tune_tier"] = profile.get("_opt_tier")
        return merged
    except Exception:
        # Auto-tune must never break config loading — fall back to the raw cfg.
        return cfg
