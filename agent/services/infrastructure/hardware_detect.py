"""
Hardware detection for Layla. Detects CPU, RAM, GPU, acceleration backend,
machine tier. Single source of truth for hardware analysis.
Used by runtime_safety, first_run, model_recommender, and installer.
"""
from __future__ import annotations

import os
import platform
import subprocess
from pathlib import Path

_logger = __import__("logging").getLogger("layla")

_cache: dict | None = None


def _detect_cpu_model() -> str:
    """Detect CPU model name for display."""
    try:
        if platform.system() == "Windows":
            try:
                r = subprocess.run(
                    ["wmic", "cpu", "get", "name"],
                    capture_output=True, text=True, timeout=5,
                    encoding="utf-8", errors="replace",
                )
                if r.returncode == 0 and r.stdout.strip():
                    lines = [ln.strip() for ln in r.stdout.strip().splitlines() if ln.strip()]
                    if len(lines) >= 2:
                        return lines[1].strip() or "Unknown CPU"
            except (FileNotFoundError, OSError):
                pass
            return platform.processor() or "Unknown CPU"
        if platform.system() == "Linux":
            try:
                with open("/proc/cpuinfo", encoding="utf-8", errors="replace") as f:
                    for line in f:
                        if line.startswith("model name"):
                            return line.split(":", 1)[1].strip() or "Unknown CPU"
            except OSError:
                pass
        if platform.system() == "Darwin":
            r = subprocess.run(
                ["sysctl", "-n", "machdep.cpu.brand_string"],
                capture_output=True, text=True, timeout=5,
            )
            if r.returncode == 0 and r.stdout.strip():
                return r.stdout.strip()
    except Exception:
        pass
    return platform.processor() or "Unknown CPU"


def detect_hardware() -> dict:
    """
    Detect hardware capabilities. Returns structured result.
    Cached per process.

    Returns:
        {
            "cpu_cores": int,
            "cpu_physical": int | None,
            "ram_gb": float,
            "gpu_name": str,
            "vram_gb": float,
            "acceleration_backend": str,  # "cuda" | "rocm" | "metal" | "none"
            "machine_tier": str,  # "tier1" | "tier2" | "tier3" | "tier4"
            "disk_speed_mbps": float | None,  # optional, may be None
        }
    """
    global _cache
    if _cache is not None:
        return _cache

    cpu_cores = os.cpu_count() or 4
    cpu_physical: int | None = None
    try:
        import psutil
        cpu_physical = psutil.cpu_count(logical=False) or cpu_cores
    except Exception:
        pass

    ram_gb = 16.0
    try:
        import psutil
        mem = psutil.virtual_memory()
        ram_gb = round(mem.total / (1024**3), 1)
    except Exception:
        pass

    gpu_name = "none"
    vram_gb = 0.0
    acceleration_backend = "none"

    # NVIDIA CUDA
    try:
        r = subprocess.run(
            ["nvidia-smi", "--query-gpu=name,memory.total", "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=10, encoding="utf-8", errors="replace",
        )
        if r.returncode == 0 and r.stdout.strip():
            line = r.stdout.strip().split("\n")[0]
            parts = line.split(",")
            if len(parts) >= 2:
                gpu_name = parts[0].strip().replace('"', "")
                raw = parts[1].strip().replace("MiB", "").replace("MB", "").strip()
                try:
                    vram_mb = int(raw)
                    vram_gb = round(vram_mb / 1024.0, 1)
                except ValueError:
                    pass
            acceleration_backend = "cuda"
    except Exception:
        pass

    # AMD ROCm (if NVIDIA not found)
    if acceleration_backend == "none":
        try:
            r = subprocess.run(
                ["rocm-smi", "--showmeminfo", "vram"],
                capture_output=True, text=True, timeout=8,
            )
            if r.returncode == 0 and "Total Memory" in (r.stdout or ""):
                for line in (r.stdout or "").splitlines():
                    if "Total Memory" in line:
                        try:
                            kb = int(line.split(":")[1].strip().split()[0])
                            vram_gb = round(kb / (1024 * 1024), 1)
                        except (ValueError, IndexError):
                            pass
                        break
                gpu_name = "AMD (ROCm)"
                acceleration_backend = "rocm"
        except Exception:
            pass

    # Metal (macOS) — assume available on Darwin with Apple Silicon or Intel Mac
    if acceleration_backend == "none" and platform.system() == "Darwin":
        try:
            # Check for Apple Silicon
            mach = platform.machine().lower()
            if mach in ("arm64", "aarch64"):
                gpu_name = "Apple Silicon (Metal)"
                acceleration_backend = "metal"
            else:
                gpu_name = "Intel Mac (Metal)"
                acceleration_backend = "metal"
        except Exception:
            pass

    machine_tier = _classify_machine_tier(ram_gb, vram_gb)
    cpu_model = _detect_cpu_model()

    disk_speed_mbps: float | None = None
    try:
        disk_speed_mbps = _probe_disk_speed()
    except Exception:
        pass

    _cache = {
        "cpu_model": cpu_model,
        "cpu_cores": cpu_cores,
        "cpu_physical": cpu_physical,
        "ram_gb": ram_gb,
        "gpu_name": gpu_name,
        "vram_gb": vram_gb,
        "acceleration_backend": acceleration_backend,
        "machine_tier": machine_tier,
        "disk_speed_mbps": disk_speed_mbps,
    }
    return _cache


def _classify_machine_tier(ram_gb: float, vram_gb: float) -> str:
    """
    Classify machine: tier1 (laptop), tier2 (gaming), tier3 (workstation), tier4 (server).
    """
    if vram_gb >= 24 or ram_gb >= 64:
        return "tier4"
    if vram_gb >= 12 or ram_gb >= 32:
        return "tier3"
    if vram_gb >= 6 or ram_gb >= 16:
        return "tier2"
    return "tier1"


def _probe_disk_speed() -> float | None:
    """
    Rough disk write speed in MB/s. Returns None if unmeasurable.
    Uses a small temp file write; may be inaccurate.
    """
    import tempfile
    import time

    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=".tmp") as f:
            path = Path(f.name)
        data = b"x" * (4 * 1024 * 1024)  # 4 MB
        start = time.perf_counter()
        path.write_bytes(data)
        elapsed = time.perf_counter() - start
        path.unlink(missing_ok=True)
        if elapsed > 0:
            return round(4.0 / elapsed, 1)
    except Exception:
        pass
    return None


def classify_hardware(hardware_info: dict) -> dict[str, str]:
    """
    Classify hardware into tiers for model selection.

    Returns:
        {
            "cpu_tier": str,   # "low" | "medium" | "high"
            "ram_tier": str,   # "low" | "medium" | "high" | "very_high"
            "gpu_tier": str,   # "none" | "low" | "medium" | "high" | "very_high"
        }
    """
    ram_gb = hardware_info.get("ram_gb", 0.0)
    vram_gb = hardware_info.get("vram_gb", 0.0)
    accel = hardware_info.get("acceleration_backend", "none")
    cpu_cores = hardware_info.get("cpu_cores", 4)

    if cpu_cores >= 16:
        cpu_tier = "high"
    elif cpu_cores >= 8:
        cpu_tier = "medium"
    else:
        cpu_tier = "low"

    effective_ram = vram_gb if accel != "none" else ram_gb
    if effective_ram >= 48 or ram_gb >= 64:
        ram_tier = "very_high"
    elif effective_ram >= 24 or ram_gb >= 32:
        ram_tier = "high"
    elif effective_ram >= 8 or ram_gb >= 16:
        ram_tier = "medium"
    else:
        ram_tier = "low"

    if accel == "none":
        gpu_tier = "none"
    elif vram_gb >= 24:
        gpu_tier = "very_high"
    elif vram_gb >= 12:
        gpu_tier = "high"
    elif vram_gb >= 6:
        gpu_tier = "medium"
    elif vram_gb >= 2:
        gpu_tier = "low"
    else:
        gpu_tier = "none"

    return {
        "cpu_tier": cpu_tier,
        "ram_tier": ram_tier,
        "gpu_tier": gpu_tier,
    }


def clear_cache() -> None:
    """Clear hardware cache (e.g. for tests)."""
    global _cache
    _cache = None


def hardware_class(hw: dict | None = None) -> str:
    """Coarse class for adaptive budgets: potato | mid | strong | workstation."""
    h = hw if hw is not None else detect_hardware()
    tier = str(h.get("machine_tier") or "tier2")
    if tier == "tier1":
        return "potato"
    if tier == "tier2":
        return "mid"
    if tier == "tier3":
        return "strong"
    return "workstation"


# ---------------------------------------------------------------------------
# Optimal settings recommendation (builds on detect_hardware())
# ---------------------------------------------------------------------------

_TIER_MAP = {"tier1": "potato", "tier2": "standard", "tier3": "performance", "tier4": "high_end"}
_TIER_CTX = {"potato": 2048, "standard": 4096, "performance": 4096, "high_end": 8192}
_TIER_BATCH = {"potato": 512, "standard": 1024, "performance": 2048, "high_end": 2048}
_TIER_RATIO = {"potato": 0.65, "standard": 0.70, "performance": 0.75, "high_end": 0.75}

def get_recommended_settings(hw: dict | None = None) -> dict:
    """
    Return recommended llama-cpp-python config settings for this hardware.
    Config-file explicit values should always override these.
    """
    h = hw if hw is not None else detect_hardware()
    tier_raw = str(h.get("machine_tier") or "tier2")
    tier = _TIER_MAP.get(tier_raw, "standard")
    ram_gb = h.get("ram_gb", 16.0)
    vram_gb = h.get("vram_gb", 0.0)
    cpu_physical = h.get("cpu_physical") or h.get("cpu_cores", 4)
    cpu_logical = h.get("cpu_cores", 4)
    has_gpu = (h.get("acceleration_backend") or "none") != "none"

    n_ctx = _TIER_CTX[tier]

    # Adjust n_ctx for model size vs RAM headroom
    try:
        import runtime_safety
        cfg = runtime_safety.load_config() or {}
        model_path = (cfg.get("model_path") or cfg.get("model_filename") or "").strip()
        if model_path:
            from pathlib import Path as _Path
            p = _Path(model_path)
            if p.exists():
                model_mb = p.stat().st_size // (1024 * 1024)
                ram_mb = int(ram_gb * 1024)
                headroom_mb = max(0, ram_mb - model_mb - 512)
                scale = max(0.05, model_mb / 3800)
                safe_ctx = max(512, int((headroom_mb / (0.5 * scale)) * 1024))
                n_ctx = min(n_ctx, safe_ctx)
    except Exception:
        pass
    n_ctx = max(512, (n_ctx // 512) * 512)

    # GPU layers
    if not has_gpu:
        n_gpu_layers = 0
    elif vram_gb >= 8:
        n_gpu_layers = -1
    elif vram_gb >= 4:
        n_gpu_layers = -1
    elif vram_gb > 0:
        n_gpu_layers = int(vram_gb * 4)  # rough: ~4 layers per GB
    else:
        n_gpu_layers = 0

    return {
        "n_ctx": n_ctx,
        "n_batch": _TIER_BATCH[tier],
        "n_threads": max(1, cpu_physical),
        "n_threads_batch": min(cpu_logical, cpu_physical * 2),
        "n_gpu_layers": n_gpu_layers,
        "flash_attn": has_gpu and tier in ("performance", "high_end"),
        "speculative_decoding_enabled": False,  # llama-cpp <=0.3.16 crash bug
        "context_aggressive_compress_enabled": tier in ("potato", "standard"),
        "context_auto_compact_ratio": _TIER_RATIO[tier],
        "_tier": tier,
    }


def apply_to_config(cfg: dict, hw: dict | None = None) -> dict:
    """
    Overlay hardware-recommended settings onto cfg dict.
    Config-file explicit values always win -- only fills gaps where value is None/empty.
    Returns a new merged dict.
    """
    recs = get_recommended_settings(hw)
    merged = dict(cfg)
    _PROBE_KEYS = {
        "n_ctx", "n_batch", "n_threads", "n_threads_batch",
        "n_gpu_layers", "flash_attn", "speculative_decoding_enabled",
        "context_aggressive_compress_enabled", "context_auto_compact_ratio",
    }
    for k, v in recs.items():
        if k in _PROBE_KEYS and (cfg.get(k) is None or cfg.get(k) == ""):
            merged[k] = v
    return merged


def get_capability_summary(hw: dict | None = None) -> str:
    """
    One-to-three sentence capability summary injected into system prompt.
    Layla uses this to accurately describe her own hardware limits.
    """
    h = hw if hw is not None else detect_hardware()
    recs = get_recommended_settings(h)
    tier = recs.get("_tier", "standard")
    n_ctx = recs.get("n_ctx", 4096)
    ram_gb = h.get("ram_gb", 0.0)
    vram_gb = h.get("vram_gb", 0.0)
    has_gpu = (h.get("acceleration_backend") or "none") != "none"

    ram_str = f"{int(ram_gb)} GB RAM"
    gpu_str = f" + {vram_gb:.0f} GB VRAM GPU" if (has_gpu and vram_gb > 0) else (", CPU-only" if not has_gpu else "")

    # Estimate model params from file size
    model_params = 0.0
    try:
        import runtime_safety
        cfg = runtime_safety.load_config() or {}
        mp = (cfg.get("model_path") or cfg.get("model_filename") or "").strip()
        if mp:
            from pathlib import Path as _Path
            p = _Path(mp)
            if p.exists():
                model_params = round(p.stat().st_size / (1024 * 1024 * 550), 1)
    except Exception:
        pass
    model_str = (
        f"~{model_params:.0f}B param model" if model_params >= 1 else "sub-1B (very small) model"
    )

    tier_notes = {
        "potato": (
            "Running on constrained hardware with a small model. "
            "Context window is tight; complex reasoning may time out. Best on short focused tasks."
        ),
        "standard": (
            "Running on mid-range hardware. "
            "Most tasks work; very long documents or deep reasoning chains may be slower."
        ),
        "performance": (
            "Running on capable hardware. "
            "Long contexts, code reasoning, and multi-step tasks are handled well."
        ),
        "high_end": (
            "Running on high-end hardware with a large context window. "
            "Very long documents, complex reasoning, and extended autonomous runs are supported."
        ),
    }
    note = tier_notes.get(tier, "")
    return (
        f"[Hardware: {ram_str}{gpu_str} | {model_str} | context window: {n_ctx} tokens | tier: {tier}] "
        f"{note}"
    )
