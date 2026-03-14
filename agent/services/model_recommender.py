"""
Model recommendation engine. Based on hardware detection, recommends
models with quantization, context size, and GPU layers.
"""
from __future__ import annotations

from typing import Any


def recommend(
    ram_gb: float | None = None,
    vram_gb: float | None = None,
    gpu_vendor: str = "none",
    hardware: dict | None = None,
) -> dict[str, Any]:
    """
    Recommend model settings based on hardware.

    Args:
        ram_gb: Total RAM in GB. If None, uses hardware["ram_gb"].
        vram_gb: GPU VRAM in GB. If None, uses hardware["vram_gb"].
        gpu_vendor: "nvidia" | "amd" | "none".
        hardware: Optional pre-detected hardware dict from hardware_detect.detect_hardware().

    Returns:
        {
            "model_name": str,
            "quantization": str,
            "context_size": int,
            "gpu_layers": int,
            "n_batch": int,
            "completion_max_tokens": int,
            "model_tier": str,
            "suggestion": str,
        }
    """
    if hardware is not None:
        ram_gb = ram_gb if ram_gb is not None else hardware.get("ram_gb", 16.0)
        vram_gb = vram_gb if vram_gb is not None else hardware.get("vram_gb", 0.0)
        accel = hardware.get("acceleration_backend", "none")
        gpu_vendor = "nvidia" if accel == "cuda" else "amd" if accel == "rocm" else "none"
    ram_gb = ram_gb if ram_gb is not None else 16.0
    vram_gb = vram_gb if vram_gb is not None else 0.0

    # Rule set: <4GB VRAM → 3B–7B Q4; 6–8GB → 7B–13B; 12–24GB → 13B–34B; >48GB → 70B+
    if vram_gb >= 48 or (gpu_vendor == "none" and ram_gb >= 64):
        return {
            "model_name": "Qwen2.5-72B-Instruct-Q4_K_M",
            "quantization": "Q4_K_M",
            "context_size": 8192,
            "gpu_layers": -1,
            "n_batch": 1024,
            "completion_max_tokens": 512,
            "model_tier": "large",
            "suggestion": "Qwen2.5-72B-Instruct-Q4_K_M or Llama-3.3-70B-Instruct-Q4_K_M",
        }
    if vram_gb >= 24 or (gpu_vendor == "none" and ram_gb >= 48):
        return {
            "model_name": "Qwen2.5-32B-Instruct-Q4_K_M",
            "quantization": "Q4_K_M",
            "context_size": 8192,
            "gpu_layers": -1,
            "n_batch": 1024,
            "completion_max_tokens": 512,
            "model_tier": "large",
            "suggestion": "Qwen2.5-32B-Instruct-Q4_K_M or DeepSeek-R1-Distill-Qwen-32B-Q4_K_M",
        }
    if vram_gb >= 16 or (gpu_vendor == "none" and ram_gb >= 32):
        return {
            "model_name": "Qwen2.5-14B-Instruct-Q5_K_M",
            "quantization": "Q5_K_M",
            "context_size": 8192,
            "gpu_layers": -1,
            "n_batch": 512,
            "completion_max_tokens": 512,
            "model_tier": "medium-large",
            "suggestion": "Qwen2.5-14B-Instruct-Q5_K_M or Mistral-NeMo-12B-Instruct-Q5_K_M",
        }
    if vram_gb >= 8 or (gpu_vendor == "none" and ram_gb >= 16):
        return {
            "model_name": "Qwen2.5-7B-Instruct-Q5_K_M",
            "quantization": "Q5_K_M",
            "context_size": 4096,
            "gpu_layers": -1,
            "n_batch": 512,
            "completion_max_tokens": 384,
            "model_tier": "medium",
            "suggestion": "Qwen2.5-7B-Instruct-Q5_K_M or Llama-3.2-8B-Instruct-Q4_K_M",
        }
    if vram_gb >= 6:
        return {
            "model_name": "Qwen2.5-7B-Instruct-Q4_K_M",
            "quantization": "Q4_K_M",
            "context_size": 4096,
            "gpu_layers": -1,
            "n_batch": 256,
            "completion_max_tokens": 256,
            "model_tier": "medium",
            "suggestion": "Qwen2.5-7B-Instruct-Q4_K_M or Llama-3.2-8B-Instruct-Q4_K_M",
        }
    if vram_gb >= 4 or (gpu_vendor == "none" and ram_gb >= 8):
        return {
            "model_name": "Phi-3.5-mini-instruct-Q4_K_M",
            "quantization": "Q4_K_M",
            "context_size": 2048,
            "gpu_layers": 20,
            "n_batch": 256,
            "completion_max_tokens": 256,
            "model_tier": "small",
            "suggestion": "Phi-3.5-mini-instruct-Q4_K_M or Llama-3.2-3B-Instruct-Q8_0",
        }
    if vram_gb >= 2:
        return {
            "model_name": "Llama-3.2-3B-Instruct-Q4_K_M",
            "quantization": "Q4_K_M",
            "context_size": 2048,
            "gpu_layers": 10,
            "n_batch": 128,
            "completion_max_tokens": 256,
            "model_tier": "small",
            "suggestion": "Llama-3.2-3B-Instruct-Q8_0 or Phi-3.5-mini-Q4_K_M",
        }
    # CPU-only or very low resource
    return {
        "model_name": "Llama-3.2-1B-Instruct-Q8_0",
        "quantization": "Q8_0",
        "context_size": 1024,
        "gpu_layers": 0,
        "n_batch": 128,
        "completion_max_tokens": 256,
        "model_tier": "tiny",
        "suggestion": "Llama-3.2-1B-Instruct-Q8_0 or Phi-3.5-mini-Q4_K_M",
    }


def recommend_from_hardware() -> dict[str, Any]:
    """Recommend using current hardware detection."""
    try:
        from services.hardware_detect import detect_hardware
        return recommend(hardware=detect_hardware())
    except Exception:
        return recommend(ram_gb=16.0, vram_gb=0.0, gpu_vendor="none")
