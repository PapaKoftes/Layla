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
    _rs.CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
    _rs.CONFIG_FILE.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
    _rs.invalidate_config_cache()

