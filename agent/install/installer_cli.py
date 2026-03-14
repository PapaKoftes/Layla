"""
Layla interactive installer CLI.
Detects hardware, recommends model, downloads it, generates runtime_config.json.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

# Ensure agent dir is on path when run as script (install is under agent/)
AGENT_DIR = Path(__file__).resolve().parent.parent
REPO_ROOT = AGENT_DIR.parent
# Add agent dir so "install" package is found (agent/install/)
for p in (AGENT_DIR, REPO_ROOT):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

CONFIG_PATH = AGENT_DIR / "runtime_config.json"


def _yn(prompt: str, default: bool = True) -> bool:
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


def _ask(prompt: str, default: str = "") -> str:
    try:
        ans = input(f"{prompt} [{default}]: ").strip()
        return ans if ans else default
    except (EOFError, KeyboardInterrupt):
        return default


def _generate_runtime_config(
    hardware_info: dict,
    model_filename: str,
    models_dir: str,
    sandbox_root: str,
) -> dict:
    """
    Auto-generate runtime config from hardware.
    Sets n_ctx, n_threads, n_gpu_layers, parallel_tasks.
    """
    ram_gb = hardware_info.get("ram_gb", 16.0)
    vram_gb = hardware_info.get("vram_gb", 0.0)
    cpu_cores = hardware_info.get("cpu_cores", 4)
    cpu_physical = hardware_info.get("cpu_physical") or cpu_cores
    accel = hardware_info.get("acceleration_backend", "none")

    # n_ctx: context window. Larger = more memory. Tuned for shitty PCs.
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
        n_ctx = 512  # Ultra-low: 4GB or less

    # n_threads: physical cores, leave one free, cap at 16. Old CPUs: min 1.
    n_threads = max(1, min(cpu_physical - 1, 16)) if cpu_physical else max(1, min(cpu_cores - 1, 16))

    # n_gpu_layers: -1 = all to GPU when available; 0 = CPU only
    if accel != "none" and vram_gb >= 4:
        n_gpu_layers = -1
    elif accel != "none" and vram_gb >= 2:
        n_gpu_layers = 20
    else:
        n_gpu_layers = 0

    # parallel_tasks: for task graph. Scale with cores. Cap low for weak PCs.
    parallel_tasks = max(2, min(cpu_cores, 8))

    # n_batch: smaller for low memory to avoid OOM
    if n_ctx >= 4096:
        n_batch = min(1024, n_ctx)
    elif n_ctx >= 1024:
        n_batch = min(512, n_ctx)
    else:
        n_batch = min(256, n_ctx)
    completion_max_tokens = 512 if n_ctx >= 4096 else (256 if n_ctx >= 1024 else 128)

    # use_mlock: only beneficial with large RAM
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


def run() -> int:
    """Interactive installer. Returns 0 on success."""
    try:
        from install.model_downloader import download_model, get_canonical_models_dir
        from install.model_selector import recommend_model
        from services.hardware_detect import classify_hardware, detect_hardware
    except ImportError as e:
        raise ImportError(f"Installer dependencies missing: {e}. Run from repo root with venv activated.") from e

    print()
    print("  ∴  Layla — First-Run Installer")
    print("  ─────────────────────────────────")
    print()

    # 1. Detect hardware (single source: services.hardware_detect)
    print("  [1/6]  Detecting hardware...")
    try:
        hardware = detect_hardware()
    except Exception as e:
        raise RuntimeError(f"Hardware detection failed: {e}") from e
    tiers = classify_hardware(hardware)

    print(f"      CPU  : {hardware.get('cpu_model', 'Unknown')} ({hardware.get('cpu_cores', 4)} cores)")
    print(f"      RAM  : {hardware.get('ram_gb', 0):.0f} GB")
    gpu_name = hardware.get("gpu_name", "none")
    vram = hardware.get("vram_gb", 0)
    if gpu_name != "none":
        print(f"      GPU  : {gpu_name} ({vram:.0f} GB VRAM)")
    else:
        print("      GPU  : none (CPU inference)")
    print(f"      Tier : {hardware.get('machine_tier', '?')} | CPU={tiers['cpu_tier']}, RAM={tiers['ram_tier']}, GPU={tiers['gpu_tier']}")
    print()

    # 2. Recommend model from catalog (hardware-aware)
    print("  [2/6]  Recommending model for your hardware...")
    recommended = recommend_model(hardware)
    if not recommended:
        print("      [!] No compatible model in catalog. See MODELS.md for manual download.")
        model_filename = ""
    else:
        print(f"      Recommended: {recommended.get('name', 'Unknown')}")
        print(f"      {recommended.get('desc', '')}")
        print()

        if not _yn("  Download this model?", True):
            model_filename = _ask("  Enter model filename (or leave blank to skip)", "")
            if not model_filename:
                model_filename = ""
        else:
            # 3. Download to canonical models dir (ONE spot)
            print()
            print("  [3/6]  Downloading model...")
            canonical_dir = get_canonical_models_dir()
            canonical_dir.mkdir(parents=True, exist_ok=True)
            result = download_model(recommended, models_dir=canonical_dir, progress=True)
            if result.get("ok"):
                model_filename = result.get("filename", "")
                print(f"      ✓  Saved to {canonical_dir / model_filename}")
            else:
                print(f"      [!] Download failed: {result.get('error', 'Unknown')}")
                print("      See MODELS.md for manual download links.")
                model_filename = ""

    # Canonical dir: the ONE place models live
    canonical_dir = get_canonical_models_dir()
    existing_models = sorted(canonical_dir.glob("*.gguf")) if canonical_dir.exists() else []
    model_to_name = {p.name: p for p in existing_models}

    if not model_filename:
        # Check for existing models in canonical dir only
        if model_to_name:
            print()
            print(f"  Existing models in {canonical_dir} :")
            names = sorted(model_to_name.keys())
            for i, name in enumerate(names, 1):
                print(f"      [{i}] {name}")
            choice = _ask("  Enter number to use (or Enter to skip)", "1")
            try:
                idx = int(choice) - 1
                if 0 <= idx < len(names):
                    model_filename = names[idx]
            except ValueError:
                pass

    # 4. Config — ALWAYS set models_dir to canonical dir
    print()
    print("  [4/6]  Generating runtime config...")

    existing_cfg = {}
    if CONFIG_PATH.exists():
        try:
            existing_cfg = json.loads(CONFIG_PATH.read_text(encoding="utf-8-sig"))
        except Exception:
            try:
                existing_cfg = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
            except Exception:
                pass
        if existing_cfg and not _yn("  Existing config found. Overwrite?", True):
            print("      Keeping existing config.")
            return 0

    # models_dir is ALWAYS the canonical dir (one spot)
    models_dir_str = str(canonical_dir.resolve())
    sandbox = _ask("  Default workspace path (folder Layla can read/write)", str(Path.home()))
    sandbox = sandbox or str(Path.home())

    cfg = _generate_runtime_config(hardware, model_filename or "", models_dir_str, sandbox)

    # Merge non-overwritten keys from existing
    for key, val in existing_cfg.items():
        if key not in ("n_ctx", "n_threads", "n_gpu_layers", "n_batch", "completion_max_tokens",
                       "model_filename", "models_dir", "sandbox_root"):
            cfg.setdefault(key, val)

    try:
        CONFIG_PATH.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
    except OSError as e:
        raise OSError(f"Could not write config to {CONFIG_PATH}: {e}") from e

    # 5. Benchmark (optional, after config is written)
    if model_filename:
        print()
        print("  [5/6]  Benchmarking model (tokens/sec, latency, memory)...")
        print("        This may take a minute to load the model...")
        try:
            # Invalidate config cache so we read the fresh config
            import runtime_safety
            if hasattr(runtime_safety, "_config_cache"):
                runtime_safety._config_cache = None
            from services.model_benchmark import run_benchmark
            bench = run_benchmark(model_filename)
            if bench.get("ok"):
                tps = bench.get("tokens_per_sec", 0)
                lat = bench.get("first_token_ms", 0)
                mem = bench.get("memory_mb", 0)
                print(f"        ✓  {tps:.1f} tokens/sec, {lat:.0f} ms first token, {mem:.0f} MB RSS")
                print("        ✓  Stored in ~/.layla/benchmarks.json")
            else:
                print(f"        [!] Benchmark skipped: {bench.get('error', 'Unknown')}")
        except Exception as e:
            print(f"        [!] Benchmark skipped: {e}")
    else:
        print()
        print("  [5/6]  Skipping benchmark (no model set).")

    # 6. Done
    print()
    print("  [6/6]  Done.")
    print()
    print("  ═══════════════════════════════════════════════")
    print("   INSTALLATION COMPLETE")
    print("  ═══════════════════════════════════════════════")
    print()
    if model_filename:
        print(f"  ✓  Model: {model_filename}")
        print(f"  ✓  Config: {CONFIG_PATH}")
        print()
        print("  Run  START.bat (Windows) or  bash start.sh  (Linux/macOS)")
        print("  Layla opens at:  http://localhost:8000/ui")
    else:
        print("  !  No model set. Add a .gguf to ~/.layla/models/ or models/")
        print("     Then run this installer again or edit agent/runtime_config.json")
        print()
        print("  See MODELS.md for download links.")
    print()
    return 0


if __name__ == "__main__":
    sys.exit(run())
