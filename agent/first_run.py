"""
Layla first-run setup wizard.
Detects hardware, recommends settings, and writes agent/runtime_config.json.
Safe to re-run at any time — asks before overwriting existing settings.
"""
from __future__ import annotations
import json
import os
import subprocess
import sys
from pathlib import Path

AGENT_DIR = Path(__file__).resolve().parent
REPO_ROOT = AGENT_DIR.parent
CONFIG_PATH = AGENT_DIR / "runtime_config.json"
MODELS_DIR = REPO_ROOT / "models"


# ── Hardware probing ───────────────────────────────────────────────────────

def detect_ram_gb() -> float:
    try:
        import psutil
        return round(psutil.virtual_memory().total / (1024 ** 3), 1)
    except Exception:
        return 0.0


def detect_gpu() -> tuple[str, float]:
    """Returns (vendor, vram_gb). vendor = 'nvidia' | 'amd' | 'none'."""
    # NVIDIA
    try:
        r = subprocess.run(
            ["nvidia-smi", "--query-gpu=memory.total", "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=8,
        )
        if r.returncode == 0 and r.stdout.strip():
            mb = int(r.stdout.strip().split("\n")[0].strip())
            return "nvidia", round(mb / 1024, 1)
    except Exception:
        pass
    # AMD / ROCm
    try:
        r = subprocess.run(["rocm-smi", "--showmeminfo", "vram"], capture_output=True, text=True, timeout=8)
        if r.returncode == 0 and "Total Memory" in r.stdout:
            for line in r.stdout.splitlines():
                if "Total Memory" in line:
                    kb = int(line.split(":")[1].strip().split()[0])
                    return "amd", round(kb / (1024 * 1024), 1)
    except Exception:
        pass
    return "none", 0.0


def find_models() -> list[Path]:
    MODELS_DIR.mkdir(exist_ok=True)
    return sorted(MODELS_DIR.glob("*.gguf"))


# ── Model recommendation ───────────────────────────────────────────────────

def recommend_model(ram_gb: float, vram_gb: float, gpu_vendor: str) -> dict:
    """Return recommended config settings and a model suggestion string."""
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
    # Very low resource
    return {
        "config": {"n_ctx": 1024, "n_gpu_layers": 0, "n_batch": 128,
                   "completion_max_tokens": 256, "use_mmap": True},
        "model_tier": "tiny",
        "suggestion": "Llama-3.2-1B-Instruct-Q8_0 or Phi-3.5-mini-Q4_K_M",
    }


# ── Config builder ─────────────────────────────────────────────────────────

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
    "sandbox_root": str(Path.home()),
    "safe_mode": True,
    "uncensored": True,
    "nsfw_allowed": True,
    "knowledge_unrestricted": True,
    "use_chroma": True,
    "scheduler_study_enabled": True,
    "scheduler_interval_minutes": 30,
    "enable_cot": True,
    "enable_self_reflection": False,
    "whisper_model": "base",
    "tts_voice": "af_heart",
}


def load_existing() -> dict:
    try:
        if CONFIG_PATH.exists():
            return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    except Exception:
        pass
    return {}


def save_config(cfg: dict) -> None:
    CONFIG_PATH.write_text(json.dumps(cfg, indent=2), encoding="utf-8")


# ── Interactive prompts ────────────────────────────────────────────────────

def yn(prompt: str, default: bool = True) -> bool:
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


def ask(prompt: str, default: str = "") -> str:
    try:
        ans = input(f"{prompt} [{default}]: ").strip()
        return ans if ans else default
    except (EOFError, KeyboardInterrupt):
        return default


# ── Main wizard ────────────────────────────────────────────────────────────

def run() -> int:
    print()
    print("  ∴  Layla — First-Run Setup")
    print("  ──────────────────────────────")
    print()

    # Detect hardware
    ram_gb = detect_ram_gb()
    gpu_vendor, vram_gb = detect_gpu()

    print(f"  Hardware detected:")
    print(f"    RAM   : {ram_gb:.0f} GB")
    if gpu_vendor != "none":
        print(f"    GPU   : {gpu_vendor.upper()}, {vram_gb:.0f} GB VRAM")
    else:
        print(f"    GPU   : none detected (CPU inference)")
    print()

    rec = recommend_model(ram_gb, vram_gb, gpu_vendor)
    print(f"  Recommended model tier : {rec['model_tier']}")
    print(f"  Suggested model        : {rec['suggestion']}")
    print(f"  (See MODELS.md for download links and more options)")
    print()

    # Find models already in models/
    models = find_models()
    model_filename = ""
    if models:
        print(f"  Models found in models/ :")
        for i, m in enumerate(models):
            print(f"    [{i+1}] {m.name}")
        print()
        choice = ask("  Enter the number of the model to use (or type a filename, Enter to skip)", "1")
        try:
            idx = int(choice) - 1
            if 0 <= idx < len(models):
                model_filename = models[idx].name
        except ValueError:
            if choice and (MODELS_DIR / choice).exists():
                model_filename = choice
    else:
        print("  No .gguf models found in models/")
        print("  See MODELS.md for download instructions.")
        print()
        model_filename = ask(
            "  Enter model filename if you have one elsewhere (or Enter to skip)",
            ""
        )

    # Check if config already exists
    existing = load_existing()
    if existing and not yn("  Existing config found. Update it?", True):
        print("  Keeping existing config.")
        return 0

    # Build config
    cfg = {**DEFAULTS}
    cfg.update(rec["config"])

    # Set model filename
    if model_filename:
        cfg["model_filename"] = model_filename
    elif existing.get("model_filename"):
        cfg["model_filename"] = existing["model_filename"]

    # Set sandbox to user's home by default
    cfg["sandbox_root"] = str(Path.home())

    # Ask workspace
    workspace = ask(
        "  Default workspace path (folder Layla can read/write tools in)",
        str(Path.home())
    )
    cfg["sandbox_root"] = workspace

    # Merge any custom keys from existing config
    for key, val in existing.items():
        if key not in ("n_gpu_layers", "n_ctx", "n_batch", "completion_max_tokens"):
            cfg.setdefault(key, val)

    # use_mlock: only beneficial if RAM is large
    cfg["use_mlock"] = ram_gb >= 24

    save_config(cfg)

    print()
    print("  ✓  Config saved to agent/runtime_config.json")
    if cfg.get("model_filename"):
        print(f"  ✓  Model set to: {cfg['model_filename']}")
    else:
        print("  !  No model set yet — add a .gguf to models/ and update the config.")
    print()
    print("  Run START.bat (Windows) or bash start.sh (Linux/macOS) to launch Layla.")
    print()
    return 0


if __name__ == "__main__":
    sys.exit(run())
