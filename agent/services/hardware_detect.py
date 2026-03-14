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
