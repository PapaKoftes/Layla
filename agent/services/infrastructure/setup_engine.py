"""
Shared setup logic for Layla first-run experiences (CLI + Web).

This module is intentionally dependency-light so it can be used by:
- `agent/first_run.py` (interactive CLI wizard)
- `agent/routers/settings.py` setup endpoints used by the Web UI wizard
"""
from __future__ import annotations

import json
import logging
from pathlib import Path

import runtime_safety as _rs

logger = logging.getLogger("layla")


def detect_ram_gb() -> float:
    try:
        import psutil

        return round(psutil.virtual_memory().total / (1024**3), 1)
    except Exception:
        return 0.0


def detect_gpu() -> tuple[str, float]:
    """
    Best-effort GPU detection.
    Returns: (vendor, vram_gb)
    """
    try:
        import subprocess

        # NVIDIA: nvidia-smi
        try:
            out = subprocess.check_output(
                ["nvidia-smi", "--query-gpu=memory.total", "--format=csv,noheader,nounits"],
                stderr=subprocess.DEVNULL,
                text=True,
                timeout=2,
            ).strip()
            if out:
                mb = float(out.splitlines()[0].strip())
                return "nvidia", round(mb / 1024.0, 1)
        except Exception:
            pass

        # AMD ROCm: rocm-smi (best effort; often absent)
        try:
            out = subprocess.check_output(["rocm-smi", "--showmeminfo", "vram"], stderr=subprocess.DEVNULL, text=True, timeout=2)
            for line in out.splitlines():
                if "vram total" in line.lower() and ":" in line:
                    raw = line.split(":", 1)[1].strip().split()[0]
                    mb = float(raw)
                    return "amd", round(mb / 1024.0, 1)
        except Exception:
            pass
    except Exception:
        pass
    return "none", 0.0


def recommend_model(ram_gb: float, vram_gb: float, gpu_vendor: str) -> dict:
    """
    Hardware-aware recommendation of a single-model config slice + a human suggestion string.
    """
    gpu_vendor = (gpu_vendor or "none").lower().strip()
    if ram_gb >= 48 or vram_gb >= 24:
        return {
            "config": {"n_ctx": 8192, "n_gpu_layers": -1, "n_batch": 1024, "completion_max_tokens": 512, "use_mmap": True},
            "model_tier": "large",
            "suggestion": "Dolphin Llama3 70B Q2_K (or better) if you have the RAM/VRAM",
        }
    if ram_gb >= 16 or vram_gb >= 10:
        return {
            "config": {"n_ctx": 4096, "n_gpu_layers": -1, "n_batch": 512, "completion_max_tokens": 384, "use_mmap": True},
            "model_tier": "medium",
            "suggestion": "Qwen2.5-7B-Instruct-Q5_K_M or Llama-3.2-8B-Instruct-Q4_K_M",
        }
    if vram_gb >= 4 or (gpu_vendor == "none" and ram_gb >= 8):
        return {
            "config": {"n_ctx": 2048, "n_gpu_layers": 20, "n_batch": 256, "completion_max_tokens": 256, "use_mmap": True},
            "model_tier": "small",
            "suggestion": "Phi-3.5-mini-instruct-Q4_K_M or Llama-3.2-3B-Instruct-Q8_0",
        }
    return {
        "config": {"n_ctx": 1024, "n_gpu_layers": 0, "n_batch": 128, "completion_max_tokens": 256, "use_mmap": True},
        "model_tier": "tiny",
        "suggestion": "Llama-3.2-1B-Instruct-Q8_0 or Phi-3.5-mini-Q4_K_M",
    }


DEFAULTS: dict = {
    "model_filename": "",
    "n_ctx": 4096,
    "n_gpu_layers": -1,
    "n_batch": 512,
    "n_threads": None,
    "n_threads_batch": None,
    "n_keep": 512,
    "use_mmap": True,
    "use_mlock": False,
    "flash_attn": True,
    "type_k": 8,
    "type_v": 8,
    "temperature": 0.2,
    "top_p": 0.95,
    "top_k": 40,
    "repeat_penalty": 1.1,
    "completion_max_tokens": 256,
    "stop_sequences": ["\nUser:", " User:"],
    "sandbox_root": str(Path.home() / "LaylaWorkspace"),
    "safe_mode": True,
    "uncensored": True,
    "nsfw_allowed": True,
    "knowledge_unrestricted": True,
    # Operator decision (v1-scope-decisions 2026-08-01): the content policy is a FORCED first-run
    # choice, never a silent default. This flag is False until the user has explicitly chosen; the
    # first-run flow (CLI + Web wizard) must present the choice and call apply_content_policy_choice,
    # which flips it True. A fresh install with this False means "not yet disclosed/chosen".
    "content_policy_chosen": False,
    "use_chroma": True,
    "scheduler_study_enabled": True,
    "scheduler_interval_minutes": 30,
    "enable_cot": True,
    "enable_self_reflection": False,
    "embedder_prewarm_enabled": False,
    "voice_stt_prewarm_enabled": False,
    "voice_tts_prewarm_enabled": False,
    "whisper_model": "base",
    "tts_voice": "af_heart",
}


# ── First-run choices (shared by the CLI wizard and the Web setup flow) ──────────────────────────

_PERSONA_CHOICES = {
    # persona key -> (default aspect id, model category preference for the picker)
    "companion": ("morrigan", "general"),
    "coder": ("morrigan", "coding"),
}


def content_uncensored_active(cfg: dict) -> bool:
    """True when uncensored/nsfw behavior may be applied — the runtime gate for pd02.

    The forced first-run choice only sets `content_policy_chosen` when the CLI wizard runs, but the
    friend install path (INSTALL.bat -> bootstrap -> START.bat) never invokes it, so uncensored would
    otherwise default ON silently. This gate blocks the uncensored/anti-refusal prompt content until
    the choice is made: active only if (uncensored or nsfw) AND content_policy_chosen is not False.
    Backward-compatible — an EXISTING operator config with no such key is grandfathered (missing !=
    False), so only a FRESH install (DEFAULTS sets content_policy_chosen=False) is gated until chosen.
    """
    if not (bool(cfg.get("uncensored")) or bool(cfg.get("nsfw_allowed"))):
        return False
    return cfg.get("content_policy_chosen") is not False


def apply_content_policy_choice(cfg: dict, allow_uncensored: bool) -> dict:
    """Record the operator's FORCED first-run content-policy choice (v1-scope-decisions).

    allow_uncensored=True  -> uncensored/nsfw/knowledge-unrestricted ON (the operator opted in).
    allow_uncensored=False -> all three OFF (safer).
    Either way `content_policy_chosen` becomes True, so the app never silently applies a policy the
    user has not seen. Mutates and returns cfg.
    """
    allow = bool(allow_uncensored)
    cfg["uncensored"] = allow
    cfg["nsfw_allowed"] = allow
    cfg["knowledge_unrestricted"] = allow
    cfg["content_policy_chosen"] = True
    return cfg


def apply_persona_choice(cfg: dict, persona: str) -> dict:
    """Record the operator's first-run persona choice (companion vs coder/engineer).

    Sets the default aspect + a model-category preference the picker uses so a companion-seeker
    lands on a companion-tuned model, not the coder default (#1 confuser, pd01). Unknown values
    fall back to companion. Mutates and returns cfg.
    """
    key = (persona or "").strip().lower()
    aspect, model_pref = _PERSONA_CHOICES.get(key, _PERSONA_CHOICES["companion"])
    cfg["default_aspect"] = aspect
    cfg["model_category_preference"] = model_pref
    cfg["persona_choice"] = key if key in _PERSONA_CHOICES else "companion"
    return cfg


MODELS_CATALOG = [
    {
        "key": "dolphin-mistral-7b",
        "name": "Dolphin Mistral 7B Q4_K_M",
        "filename": "dolphin-2.6-mistral-7b.Q4_K_M.gguf",
        "url": "https://huggingface.co/TheBloke/dolphin-2.6-mistral-7B-GGUF/resolve/main/dolphin-2.6-mistral-7b.Q4_K_M.gguf",
        "size_gb": 4.1,
        "ram_gb": 6,
        "desc": "Uncensored Mistral 7B. Fast, excellent instruction following. Best for most users.",
    },
    {
        "key": "dolphin-llama3-8b",
        "name": "Dolphin Llama3 8B Q4_K_M",
        "filename": "dolphin-2.9.1-llama-3-8b-Q4_K_M.gguf",
        "url": "https://huggingface.co/bartowski/dolphin-2.9.1-llama-3-8b-GGUF/resolve/main/dolphin-2.9.1-llama-3-8b-Q4_K_M.gguf",
        "size_gb": 4.9,
        "ram_gb": 8,
        "desc": "Llama 3 base — newer architecture, stronger reasoning than Mistral.",
    },
    {
        "key": "hermes-3-8b",
        "name": "Hermes 3 Llama3.1 8B Q4_K_M",
        "filename": "Hermes-3-Llama-3.1-8B-Q4_K_M.gguf",
        "url": "https://huggingface.co/bartowski/Hermes-3-Llama-3.1-8B-GGUF/resolve/main/Hermes-3-Llama-3.1-8B-Q4_K_M.gguf",
        "size_gb": 4.9,
        "ram_gb": 8,
        "desc": "Hermes NousResearch. Strong system-prompt adherence, great for aspect work.",
    },
    {
        "key": "phi3-mini",
        "name": "Phi-3 Mini 3.8B Q4_K_M",
        "filename": "Phi-3-mini-4k-instruct-q4.gguf",
        "url": "https://huggingface.co/microsoft/Phi-3-mini-4k-instruct-gguf/resolve/main/Phi-3-mini-4k-instruct-q4.gguf",
        "size_gb": 2.2,
        "ram_gb": 4,
        "desc": "Tiny but surprisingly good. For low-RAM systems (4 GB). Not uncensored.",
    },
    {
        "key": "dolphin-llama3-70b",
        "name": "Dolphin Llama3 70B Q2_K",
        "filename": "dolphin-2.9-llama3-70b-Q2_K.gguf",
        "url": "https://huggingface.co/bartowski/dolphin-2.9-llama3-70b-GGUF/resolve/main/dolphin-2.9-llama3-70b-Q2_K.gguf",
        "size_gb": 26.0,
        "ram_gb": 32,
        "desc": "Maximum capability. Needs 32+ GB RAM. Not for most systems.",
    },
]


def load_existing() -> dict:
    try:
        if _rs.CONFIG_FILE.exists():
            return json.loads(_rs.CONFIG_FILE.read_text(encoding="utf-8"))
    except Exception:
        pass
    return {}


def save_config(cfg: dict) -> None:
    _rs.atomic_write_config(cfg)

