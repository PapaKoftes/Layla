"""
Layla first-run setup wizard.
Detects hardware, recommends settings, and writes agent/runtime_config.json.
Safe to re-run at any time — asks before overwriting existing settings.
"""
from __future__ import annotations

import json
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
    "embedder_prewarm_enabled": False,
    "voice_stt_prewarm_enabled": False,
    "voice_tts_prewarm_enabled": False,
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

_MODELS_CATALOG = [
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


def _download_with_progress(url: str, dest: Path) -> bool:
    """Download a file with a simple progress indicator. Returns True on success."""
    import urllib.request

    def _progress(block_num: int, block_size: int, total_size: int) -> None:
        if total_size <= 0:
            return
        downloaded = block_num * block_size
        pct = min(100, int(downloaded * 100 / total_size))
        done = pct // 2
        bar = "█" * done + "░" * (50 - done)
        downloaded_mb = downloaded / (1024 * 1024)
        total_mb = total_size / (1024 * 1024)
        print(f"\r  [{bar}] {pct}%  {downloaded_mb:.0f}/{total_mb:.0f} MB", end="", flush=True)

    try:
        dest.parent.mkdir(parents=True, exist_ok=True)
        urllib.request.urlretrieve(url, str(dest), _progress)
        print()
        return True
    except Exception as e:
        print(f"\n  Download error: {e}")
        return False


def _offer_model_download(ram_gb: float) -> str:
    """Show a model picker and offer to download. Returns chosen filename or ''."""
    print("  No models found in models/")
    print()
    print("  Available models (recommended first):")
    print()

    # Filter and sort by ram_gb ascending, mark which are viable
    viable = [m for m in _MODELS_CATALOG if m["ram_gb"] <= (ram_gb or 99)]
    others = [m for m in _MODELS_CATALOG if m not in viable]

    rows = viable + others
    for i, m in enumerate(rows, 1):
        ok = "✓" if m in viable else "!"
        print(f"  [{i}] {ok} {m['name']}  ({m['size_gb']} GB download, needs {m['ram_gb']} GB RAM)")
        print(f"      {m['desc']}")
        print()

    print("  [d] Enter a direct URL to a .gguf file")
    print("  [s] Skip — I'll add a model manually later")
    print()

    choice = ask("  Choose a model to download", "1")

    if choice.lower() == "s" or not choice:
        print("  Skipping model download. See MODELS.md for instructions.")
        return ""

    if choice.lower() == "d":
        url = ask("  Paste HuggingFace .gguf direct URL", "")
        if not url:
            return ""
        fname = url.rstrip("/").split("/")[-1]
        if not fname.endswith(".gguf"):
            fname = ask("  Filename to save as (include .gguf)", "my-model.gguf")
        dest = MODELS_DIR / fname
        print(f"  Downloading {fname}...")
        if _download_with_progress(url, dest):
            print(f"  ✓  Saved: {dest}")
            return fname
        return ""

    try:
        idx = int(choice) - 1
        if idx < 0 or idx >= len(rows):
            print("  Invalid choice. Skipping.")
            return ""
        m = rows[idx]
        dest = MODELS_DIR / m["filename"]
        print(f"  Downloading {m['name']} ({m['size_gb']} GB)...")
        print("  This may take several minutes depending on your connection.")
        print()
        if _download_with_progress(m["url"], dest):
            print(f"  ✓  Model saved: {dest}")
            return m["filename"]
        else:
            print("  Download failed. Manual download URL:")
            print(f"  {m['url']}")
            print(f"  Save as: {dest}")
            return ""
    except ValueError:
        print("  Invalid choice. Skipping.")
        return ""


def run() -> int:
    print()
    print("  ∴  Layla — First-Run Setup")
    print("  ──────────────────────────────")
    print()
    print("  Layla is local-first: chats and memory stay on this machine unless you export them.")
    print("  File writes and shell commands require explicit approval in the Web UI or MCP.")
    print(f"  Read {REPO_ROOT / 'VALUES.md'} and {REPO_ROOT / 'docs' / 'ETHICAL_AI_PRINCIPLES.md'} for values and safety framing.")
    print()

    # Detect hardware
    try:
        from services.hardware_detect import detect_hardware
        h = detect_hardware()
        ram_gb = h["ram_gb"]
        vram_gb = h["vram_gb"]
        accel = h.get("acceleration_backend", "none")
        gpu_vendor = "nvidia" if accel == "cuda" else "amd" if accel == "rocm" else "none"
        if gpu_vendor == "none":
            vram_gb = 0.0
    except Exception:
        ram_gb = detect_ram_gb()
        gpu_vendor, vram_gb = detect_gpu()

    print("  Hardware detected:")
    print(f"    RAM   : {ram_gb:.0f} GB")
    if gpu_vendor != "none":
        print(f"    GPU   : {gpu_vendor.upper()}, {vram_gb:.0f} GB VRAM")
    else:
        print("    GPU   : none detected (CPU inference)")
    print()

    rec = recommend_model(ram_gb, vram_gb, gpu_vendor)
    print(f"  Recommended model tier : {rec['model_tier']}")
    print(f"  Suggested model        : {rec['suggestion']}")
    print("  (See MODELS.md for download links and more options)")
    print()

    # Find models already in models/
    models = find_models()
    model_filename = ""
    if models:
        print("  Models found in models/ :")
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
        print()
        model_filename = _offer_model_download(ram_gb)

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

    if yn("  Apply low-resource 'potato' preset (tighter limits, Chroma off)? Recommended only for weak PCs.", False):
        try:
            from config_schema import SETTINGS_PRESETS, get_editable_keys

            ek = get_editable_keys()
            for k, v in SETTINGS_PRESETS.get("potato", {}).items():
                if k in ek:
                    cfg[k] = v
            print("  ✓  Potato preset merged (see docs/POTATO_MODE.md).")
        except Exception as e:
            print(f"  [!] Potato preset skipped: {e}")

    if yn("  Customize voice defaults (TTS / Whisper) now?", False):
        cfg["tts_voice"] = ask("  tts_voice (kokoro voice id)", cfg.get("tts_voice", "af_heart"))
        cfg["whisper_model"] = ask("  whisper_model (tiny|base|small|medium)", cfg.get("whisper_model", "base"))

    if yn("  Save a Web UI theme hint in config (optional)?", False):
        cfg["ui_theme_preset"] = ask("  ui_theme_preset (gothic|dark|light)", "gothic").strip().lower() or "gothic"

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
