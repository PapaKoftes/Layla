"""
Shared setup / diagnostic checks used by installer_cli, first_run, and diagnose_startup.

Consolidates duplicated logic:
  - Diagnostic verifications (Python version, build tools, imports, config, model)
  - Interactive prompt helpers (yn, ask)
  - Runtime config generation from hardware info
"""
from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path
from typing import Any

# ── Diagnostic checks ────────────────────────────────────────────────────────


def verify_python_version() -> tuple[bool, str]:
    """Check Python >= 3.11. Returns (ok, message)."""
    v = sys.version_info
    ver_str = f"{v.major}.{v.minor}.{v.micro}"
    if v < (3, 11):
        return False, f"Python 3.11+ required, have {ver_str}"
    if v[:2] not in ((3, 11), (3, 12), (3, 13), (3, 14)):
        return True, f"Python {ver_str} — untested version, 3.11-3.14 recommended"
    return True, f"Python {ver_str}"


def verify_build_tools() -> list[tuple[str, bool, str]]:
    """Check build tools (Linux only). Returns list of (tool, ok, message)."""
    if sys.platform != "linux":
        return []
    results = []
    for cmd, pkg in [("gcc", "build-essential"), ("g++", "build-essential"), ("cmake", "cmake")]:
        if shutil.which(cmd):
            results.append((cmd, True, f"{cmd} found"))
        else:
            results.append((cmd, False, f"{cmd} not found — install: sudo apt install {pkg}"))
    return results


def verify_import(module_name: str) -> tuple[bool, str]:
    """Try importing a module. Returns (ok, message)."""
    try:
        __import__(module_name)
        return True, f"{module_name} OK"
    except Exception as e:
        return False, f"{module_name}: {e}"


def verify_core_imports() -> list[tuple[str, bool, str, bool]]:
    """Check core imports. Returns list of (module, ok, message, optional)."""
    required = ["fastapi", "uvicorn", "llama_cpp", "sentence_transformers", "psutil"]
    optional = ["chromadb", "playwright", "soundfile", "faster_whisper"]
    results = []
    for mod in required:
        ok, msg = verify_import(mod)
        results.append((mod, ok, msg, False))
    for mod in optional:
        ok, msg = verify_import(mod)
        results.append((mod, ok, msg, True))
    return results


def verify_config(agent_dir: Path | None = None) -> tuple[bool, str, Path | None]:
    """Check runtime_config.json exists. Returns (ok, message, path)."""
    try:
        import runtime_safety
        cfg_path = runtime_safety.CONFIG_FILE
    except Exception:
        if agent_dir is None:
            agent_dir = Path(__file__).resolve().parent.parent
        cfg_path = agent_dir / "runtime_config.json"
    if cfg_path.exists():
        return True, f"Config: {cfg_path}", cfg_path
    return False, "No runtime_config.json — run: python agent/first_run.py", None


def verify_model(cfg_path: Path | None = None) -> tuple[bool, str]:
    """Check model file exists. Returns (ok, message)."""
    if cfg_path is None or not cfg_path.exists():
        return False, "No config — cannot check model"
    try:
        cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
        m = cfg.get("model_filename", "")
        md = cfg.get("models_dir", "~/.layla/models")
        models_dir = Path(md).expanduser().resolve()
        model_path = models_dir / m if m else None
        if model_path and model_path.exists():
            return True, f"Model: {model_path}"
        if cfg.get("llama_server_url"):
            return True, f"Remote LLM: {cfg['llama_server_url']}"
        return False, f"No model file — place .gguf in {md}"
    except Exception as e:
        return False, f"Model check: {e}"


# ── Interactive prompt helpers ───────────────────────────────────────────────


def prompt_yn(prompt: str, default: bool = True) -> bool:
    """Ask a yes/no question. Safe against EOF/interrupt."""
    suffix = " [Y/n] " if default else " [y/N] "
    try:
        ans = input(prompt + suffix).strip().lower()
    except (EOFError, KeyboardInterrupt):
        return default
    if ans in ("y", "yes"):
        return True
    if ans in ("n", "no"):
        return False
    return default


def prompt_ask(prompt: str, default: str = "") -> str:
    """Ask for a string value. Safe against EOF/interrupt."""
    try:
        ans = input(f"{prompt} [{default}]: ").strip()
        return ans if ans else default
    except (EOFError, KeyboardInterrupt):
        return default


# ── Runtime config generation ────────────────────────────────────────────────


def generate_runtime_config(
    hardware_info: dict[str, Any],
    model_filename: str = "",
    models_dir: str = "",
    sandbox_root: str = "",
) -> dict[str, Any]:
    """
    Generate runtime_config.json from hardware info.

    Canonical source for hardware-to-config mapping. Replaces duplicate logic
    in installer_cli._generate_runtime_config() and first_run.recommend_model().

    Args:
        hardware_info: dict with ram_gb, vram_gb, cpu_cores, cpu_physical,
                       acceleration_backend.
        model_filename: .gguf filename (empty if not yet chosen).
        models_dir: path to models directory.
        sandbox_root: path to sandbox workspace.
    """
    ram_gb = hardware_info.get("ram_gb", 16.0)
    vram_gb = hardware_info.get("vram_gb", 0.0)
    cpu_cores = hardware_info.get("cpu_cores", 4)
    cpu_physical = hardware_info.get("cpu_physical") or cpu_cores
    accel = hardware_info.get("acceleration_backend", "none")

    # n_ctx: context window. Larger = more memory.
    if vram_gb >= 24 or (accel == "none" and ram_gb >= 48):
        n_ctx = 8192
    elif vram_gb >= 12 or (accel == "none" and ram_gb >= 32):
        n_ctx = 8192
    elif vram_gb >= 8 or (accel == "none" and ram_gb >= 16):
        n_ctx = 4096
    elif vram_gb >= 4 or (accel == "none" and ram_gb >= 8):
        n_ctx = 2048
    elif vram_gb >= 2 or (accel == "none" and ram_gb >= 4):
        n_ctx = 1024
    else:
        n_ctx = 512

    # n_threads: physical cores, leave one free, cap at 16.
    n_threads = max(1, min(cpu_physical - 1, 16)) if cpu_physical else max(1, min(cpu_cores - 1, 16))

    # n_gpu_layers: -1 = all to GPU; 0 = CPU only
    if accel != "none" and vram_gb >= 4:
        n_gpu_layers = -1
    elif accel != "none" and vram_gb >= 2:
        n_gpu_layers = 20
    else:
        n_gpu_layers = 0

    # parallel_tasks: scale with cores, cap for weak PCs
    parallel_tasks = max(2, min(cpu_cores, 8))

    # n_batch: smaller for low memory
    if n_ctx >= 4096:
        n_batch = min(1024, n_ctx)
    elif n_ctx >= 1024:
        n_batch = min(512, n_ctx)
    else:
        n_batch = min(256, n_ctx)

    completion_max_tokens = 512 if n_ctx >= 4096 else (256 if n_ctx >= 1024 else 128)
    use_mlock = ram_gb >= 24

    return {
        "model_filename": model_filename,
        "models_dir": models_dir,
        "sandbox_root": sandbox_root,
        "n_ctx": n_ctx,
        "n_threads": n_threads,
        "n_gpu_layers": n_gpu_layers,
        "parallel_tasks": parallel_tasks,
        "n_batch": n_batch,
        "completion_max_tokens": completion_max_tokens,
        "use_mlock": use_mlock,
        "use_mmap": True,
        "flash_attn": True,
        "type_k": 8,
        "type_v": 8,
        "temperature": 0.2,
        "top_p": 0.95,
        "top_k": 40,
        "repeat_penalty": 1.1,
        "stop_sequences": ["\nUser:", " User:"],
        "uncensored": True,
        "nsfw_allowed": True,
        "safe_mode": True,
        "use_chroma": True,
        "scheduler_study_enabled": True,
        "enable_cot": True,
        "enable_self_reflection": False,
        "whisper_model": "base",
        "tts_voice": "af_heart",
    }


def recommend_model_tier(ram_gb: float, vram_gb: float, gpu_vendor: str) -> dict[str, Any]:
    """
    Recommend a model tier and suggestion string based on hardware.

    Returns dict with 'config' (partial config overrides), 'model_tier', and 'suggestion'.
    """
    if vram_gb >= 24 or (gpu_vendor == "none" and ram_gb >= 64):
        return {
            "config": {"n_ctx": 8192, "n_gpu_layers": -1, "n_batch": 1024,
                       "completion_max_tokens": 512, "use_mmap": True},
            "model_tier": "large",
            "suggestion": "Qwen2.5-72B-Instruct-Q4_K_M or Llama-3.3-70B-Instruct-Q4_K_M",
        }
    if vram_gb >= 16 or (gpu_vendor == "none" and ram_gb >= 32):
        return {
            "config": {"n_ctx": 8192, "n_gpu_layers": -1, "n_batch": 512,
                       "completion_max_tokens": 512, "use_mmap": True},
            "model_tier": "medium-large",
            "suggestion": "Qwen2.5-14B-Instruct-Q5_K_M or Mistral-NeMo-12B-Instruct-Q5_K_M",
        }
    if vram_gb >= 8 or (gpu_vendor == "none" and ram_gb >= 16):
        return {
            "config": {"n_ctx": 4096, "n_gpu_layers": -1, "n_batch": 512,
                       "completion_max_tokens": 384, "use_mmap": True},
            "model_tier": "medium",
            "suggestion": "Qwen2.5-7B-Instruct-Q5_K_M or Llama-3.2-8B-Instruct-Q4_K_M",
        }
    if vram_gb >= 4 or (gpu_vendor == "none" and ram_gb >= 8):
        return {
            "config": {"n_ctx": 2048, "n_gpu_layers": 20, "n_batch": 256,
                       "completion_max_tokens": 256, "use_mmap": True},
            "model_tier": "small",
            "suggestion": "Phi-3.5-mini-instruct-Q4_K_M or Llama-3.2-3B-Instruct-Q8_0",
        }
    return {
        "config": {"n_ctx": 1024, "n_gpu_layers": 0, "n_batch": 128,
                   "completion_max_tokens": 256, "use_mmap": True},
        "model_tier": "tiny",
        "suggestion": "Llama-3.2-1B-Instruct-Q8_0 or Phi-3.5-mini-Q4_K_M",
    }
