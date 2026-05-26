"""Setup Wizard — interactive TUI installer for Layla.

Walks the user through:
1. Purpose selection (what do you need Layla for?)
2. Hardware detection (GPU, RAM, CPU)
3. Installation location
4. Model selection & download
5. Node role (QUEEN vs DRONE)
6. Cluster setup (pairing if DRONE)
7. Service installation
8. Component download
9. Verification

Usage:
    python -m install.setup_wizard
    python install/setup_wizard.py

Phase 4A of the distributed infrastructure plan.
"""
from __future__ import annotations

import json
import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any, Optional

# ── Constants ────────────────────────────────────────────────────────────

AGENT_DIR = Path(__file__).resolve().parent.parent
REPO_ROOT = AGENT_DIR.parent
LAYLA_HOME = Path.home() / ".layla"

PURPOSE_MAP = {
    "personal_assistant": {
        "label": "Personal assistant & scheduler",
        "extras": ["core", "llm", "voice"],
        "description": "Chat, reminders, daily planning, email drafts",
    },
    "software_dev": {
        "label": "Software development & code review",
        "extras": ["core", "llm", "research"],
        "description": "Code generation, PR review, debugging, architecture",
    },
    "research": {
        "label": "Research & knowledge management",
        "extras": ["core", "llm", "research", "crawl"],
        "description": "Paper reading, web research, knowledge bases, citations",
    },
    "creative": {
        "label": "Creative writing & brainstorming",
        "extras": ["core", "llm"],
        "description": "Stories, brainstorming, content creation, ideation",
    },
    "cad_cam": {
        "label": "CAD/CAM & fabrication",
        "extras": ["core", "llm", "data"],
        "description": "CNC toolpaths, materials, feeds/speeds, DXF generation",
    },
    "data_science": {
        "label": "Data science & analysis",
        "extras": ["core", "llm", "data", "research"],
        "description": "CSV analysis, statistics, visualisation, ML",
    },
    "all": {
        "label": "All of the above (full install)",
        "extras": ["all"],
        "description": "Everything Layla can do — largest download (~3.5 GB)",
    },
}

MODEL_RECOMMENDATIONS = {
    "gpu_high": {
        "name": "Qwen2.5-14B-Q5_K_M",
        "size_gb": 9.4,
        "description": "Best quality — your GPU can handle it",
    },
    "gpu_mid": {
        "name": "Qwen2.5-7B-Q5_K_M",
        "size_gb": 5.1,
        "description": "Great balance of quality and speed",
    },
    "gpu_low": {
        "name": "Qwen2.5-3B-Q5_K_M",
        "size_gb": 2.3,
        "description": "Fits your VRAM comfortably",
    },
    "cpu": {
        "name": "Qwen2.5-3B-Q4_K_M",
        "size_gb": 1.9,
        "description": "Optimised for CPU-only inference",
    },
}


# ── Helpers ──────────────────────────────────────────────────────────────

def _print_header():
    print()
    print("  ∴  LAYLA — Setup Wizard")
    print("  ─────────────────────────")
    print()
    print("  Welcome. I'm going to set up Layla on this machine.")
    print("  This takes about 10-20 minutes depending on your choices.")
    print()


def _print_step(step: int, total: int, title: str):
    print()
    print(f"  [{step}/{total}]  {title}")
    print(f"  {'─' * (len(title) + 8)}")
    print()


def _ask_choice(prompt: str, options: list[tuple[str, str]], allow_multiple: bool = False) -> list[str]:
    """Ask the user to pick from numbered options."""
    for i, (key, label) in enumerate(options, 1):
        print(f"    [{i}] {label}")
    print()

    if allow_multiple:
        raw = input(f"  {prompt} (comma-separated numbers, e.g. 1,3): ").strip()
        indices = []
        for part in raw.split(","):
            part = part.strip()
            if part.isdigit():
                idx = int(part) - 1
                if 0 <= idx < len(options):
                    indices.append(options[idx][0])
        return indices or [options[0][0]]
    else:
        raw = input(f"  {prompt}: ").strip()
        if raw.isdigit():
            idx = int(raw) - 1
            if 0 <= idx < len(options):
                return [options[idx][0]]
        return [options[0][0]]


def _ask_yn(prompt: str, default: bool = True) -> bool:
    """Ask a yes/no question."""
    suffix = "(Y/n)" if default else "(y/N)"
    raw = input(f"  {prompt} {suffix}: ").strip().lower()
    if not raw:
        return default
    return raw in ("y", "yes")


def _ask_path(prompt: str, default: Path) -> Path:
    """Ask for a directory path."""
    raw = input(f"  {prompt} [{default}]: ").strip()
    if not raw:
        return default
    return Path(raw)


# ── Hardware detection ───────────────────────────────────────────────────

def probe_hardware() -> dict[str, Any]:
    """Detect CPU, RAM, GPU, and disk space."""
    hw: dict[str, Any] = {
        "platform": platform.system(),
        "cpu_count": os.cpu_count() or 1,
        "cpu_name": platform.processor() or "Unknown",
    }

    # RAM
    try:
        import psutil
        mem = psutil.virtual_memory()
        hw["ram_gb"] = round(mem.total / (1024**3), 1)
    except ImportError:
        hw["ram_gb"] = 0

    # GPU
    hw["gpu_name"] = "None detected"
    hw["vram_gb"] = 0
    hw["hardware_tier"] = "cpu"

    # Try NVIDIA
    try:
        result = subprocess.run(
            ["nvidia-smi", "--query-gpu=name,memory.total", "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=5,
        )
        if result.returncode == 0 and result.stdout.strip():
            parts = result.stdout.strip().split(",")
            hw["gpu_name"] = parts[0].strip()
            vram_mb = float(parts[1].strip())
            hw["vram_gb"] = round(vram_mb / 1024, 1)
            if hw["vram_gb"] >= 16:
                hw["hardware_tier"] = "gpu_high"
            elif hw["vram_gb"] >= 8:
                hw["hardware_tier"] = "gpu_mid"
            else:
                hw["hardware_tier"] = "gpu_low"
    except Exception:
        pass

    # Disk space
    try:
        disk = shutil.disk_usage(str(LAYLA_HOME.parent))
        hw["disk_free_gb"] = round(disk.free / (1024**3), 1)
    except Exception:
        hw["disk_free_gb"] = 0

    return hw


# ── Setup steps ──────────────────────────────────────────────────────────

def step_purpose() -> list[str]:
    """Step 1: What do you want Layla to help with?"""
    _print_step(1, 8, "What would you like Layla to help with?")

    options = [(k, f"{v['label']} — {v['description']}") for k, v in PURPOSE_MAP.items()]
    choices = _ask_choice("Choose one or more", options, allow_multiple=True)

    # Collect all extras
    all_extras: set[str] = set()
    for choice in choices:
        if choice in PURPOSE_MAP:
            all_extras.update(PURPOSE_MAP[choice]["extras"])

    print()
    print(f"  Selected: {', '.join(choices)}")
    print(f"  Components to install: {', '.join(sorted(all_extras))}")

    return sorted(all_extras)


def step_hardware() -> dict[str, Any]:
    """Step 2: Hardware detection."""
    _print_step(2, 8, "Detecting your hardware...")

    hw = probe_hardware()

    print(f"    CPU:  {hw['cpu_name']} ({hw['cpu_count']} cores)")
    print(f"    RAM:  {hw['ram_gb']} GB")
    print(f"    GPU:  {hw['gpu_name']} ({hw['vram_gb']} GB VRAM)")
    print(f"    Disk: {hw['disk_free_gb']} GB free")
    print(f"    Tier: {hw['hardware_tier']}")

    return hw


def step_location() -> Path:
    """Step 3: Where should Layla live?"""
    _print_step(3, 8, "Installation location")

    default = LAYLA_HOME
    print(f"    Default: {default}")
    try:
        disk = shutil.disk_usage(str(default.parent))
        print(f"    Free space: {round(disk.free / (1024**3), 1)} GB")
    except Exception:
        pass

    path = _ask_path("Install location", default)
    path.mkdir(parents=True, exist_ok=True)

    # Create subdirectories
    for sub in ("models", "data", "knowledge", "logs", "backups"):
        (path / sub).mkdir(exist_ok=True)

    print(f"  → Installing to: {path}")
    return path


def step_model(hw: dict[str, Any]) -> dict[str, Any]:
    """Step 4: Model selection."""
    _print_step(4, 8, "AI Model selection")

    tier = hw.get("hardware_tier", "cpu")
    rec = MODEL_RECOMMENDATIONS.get(tier, MODEL_RECOMMENDATIONS["cpu"])

    print(f"    Based on your hardware, I recommend:")
    print(f"    Model: {rec['name']}")
    print(f"    Size:  {rec['size_gb']} GB")
    print(f"    Why:   {rec['description']}")
    print()

    download = _ask_yn("Download this model now?", default=True)

    return {
        "model_name": rec["name"],
        "model_size_gb": rec["size_gb"],
        "download_now": download,
        "hardware_tier": tier,
    }


def step_node_role() -> dict[str, Any]:
    """Step 5: Node role selection."""
    _print_step(5, 8, "Node role")

    print("    Layla can run as:")
    print()
    options = [
        ("queen", "QUEEN (Main PC) — Full install, Windows Service, all features"),
        ("drone", "DRONE (Helper laptop) — Lightweight, processes tasks from Queen"),
    ]
    choices = _ask_choice("Is this the main PC or a helper?", options)
    role = choices[0]

    result: dict[str, Any] = {"role": role}

    if role == "drone":
        print()
        print("  To pair with your Queen, you'll need the Queen's address")
        print("  or a pairing token from the Queen's UI.")
        print()
        queen_addr = input("  Queen's address (or press Enter to scan later): ").strip()
        if queen_addr:
            result["queen_address"] = queen_addr

    return result


def step_service(role: str) -> bool:
    """Step 6: Service installation."""
    _print_step(6, 8, "Windows Service")

    if platform.system() != "Windows":
        print("    Skipping — Windows Service is only for Windows.")
        return False

    install = _ask_yn("Install Layla as a Windows Service (starts at boot)?", default=True)
    if install:
        service_script = AGENT_DIR / "install" / "install_service.ps1"
        if service_script.exists():
            print("    Installing service...")
            try:
                subprocess.run(
                    ["powershell", "-ExecutionPolicy", "Bypass", "-File", str(service_script)],
                    timeout=60,
                )
                print("    ✓ Service installed")
                return True
            except Exception as e:
                print(f"    ⚠ Service install failed: {e}")
                print("    You can install it later with: powershell -File agent\\install\\install_service.ps1")
        else:
            print(f"    ⚠ Service script not found at {service_script}")
    return False


def step_install_deps(extras: list[str]) -> bool:
    """Step 7: Install Python dependencies."""
    _print_step(7, 8, "Installing components")

    # Check if we're in a venv
    venv_path = REPO_ROOT / ".venv"
    if not venv_path.exists():
        print("    Creating virtual environment...")
        try:
            subprocess.run([sys.executable, "-m", "venv", str(venv_path)], check=True, timeout=60)
            print("    ✓ Virtual environment created")
        except Exception as e:
            print(f"    ⚠ venv creation failed: {e}")
            return False

    # Determine pip command
    if platform.system() == "Windows":
        pip = str(venv_path / "Scripts" / "pip.exe")
    else:
        pip = str(venv_path / "bin" / "pip")

    if "all" in extras:
        install_cmd = [pip, "install", "-r", str(AGENT_DIR / "requirements.txt")]
    else:
        # Use pyproject.toml extras
        extras_str = ",".join(extras)
        install_cmd = [pip, "install", "-e", f".[{extras_str}]"]

    print(f"    Installing: {', '.join(extras)}")
    print("    This may take a few minutes...")
    print()

    try:
        subprocess.run(install_cmd, timeout=600, cwd=str(REPO_ROOT))
        print()
        print("    ✓ Dependencies installed")
        return True
    except Exception as e:
        print(f"    ⚠ Installation failed: {e}")
        print("    You can retry with: pip install -r agent/requirements.txt")
        return False


def step_verify() -> dict[str, Any]:
    """Step 8: Verification."""
    _print_step(8, 8, "Verification")

    results: dict[str, Any] = {"checks": {}}

    # Check Python version
    py_ver = f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"
    results["checks"]["python"] = py_ver
    print(f"    Python: {py_ver} ✓")

    # Check key imports
    checks = [
        ("FastAPI", "fastapi"),
        ("Pydantic", "pydantic"),
        ("SQLite", "sqlite3"),
        ("psutil", "psutil"),
    ]
    for label, module in checks:
        try:
            __import__(module)
            print(f"    {label}: ✓")
            results["checks"][label.lower()] = True
        except ImportError:
            print(f"    {label}: ✗ (not installed)")
            results["checks"][label.lower()] = False

    # Check DB
    try:
        from layla.memory.migrations import migrate
        migrate()
        print("    Database: ✓ (migrated)")
        results["checks"]["database"] = True
    except Exception as e:
        print(f"    Database: ✗ ({e})")
        results["checks"]["database"] = False

    # Check models directory
    models_dir = LAYLA_HOME / "models"
    model_files = list(models_dir.glob("*.gguf")) if models_dir.exists() else []
    if model_files:
        print(f"    Models: ✓ ({len(model_files)} found)")
        results["checks"]["models"] = True
    else:
        print("    Models: ⚠ (none found — download one to start chatting)")
        results["checks"]["models"] = False

    return results


# ── Main wizard flow ─────────────────────────────────────────────────────

def run_wizard() -> dict[str, Any]:
    """Run the complete setup wizard."""
    _print_header()

    results: dict[str, Any] = {}

    # Step 1: Purpose
    extras = step_purpose()
    results["extras"] = extras

    # Step 2: Hardware
    hw = step_hardware()
    results["hardware"] = hw

    # Step 3: Location
    location = step_location()
    results["location"] = str(location)

    # Step 4: Model
    model = step_model(hw)
    results["model"] = model

    # Step 5: Node role
    role_info = step_node_role()
    results["role"] = role_info

    # Step 6: Service
    if _ask_yn("Continue with installation?", default=True):
        # Step 7: Dependencies
        step_install_deps(extras)

        # Step 6 (service): after deps are installed
        step_service(role_info["role"])

        # Step 8: Verify
        verification = step_verify()
        results["verification"] = verification
    else:
        print()
        print("  Setup cancelled. You can run this wizard again anytime.")
        return results

    # Save setup config
    setup_config = {
        "purpose": extras,
        "hardware_tier": hw.get("hardware_tier", "cpu"),
        "node_role": role_info["role"],
        "location": str(location),
        "model": model.get("model_name", ""),
        "setup_complete": True,
    }
    config_path = LAYLA_HOME / "setup_config.json"
    try:
        config_path.write_text(json.dumps(setup_config, indent=2), encoding="utf-8")
    except Exception:
        pass

    # Final message
    print()
    print("  ─────────────────────────")
    print("  ∴  Layla is ready.")
    print()
    print("  To start Layla:")
    print(f"    cd {AGENT_DIR}")
    print("    python -m uvicorn main:app --host 127.0.0.1 --port 8000")
    print()
    print("  Or if the service is installed:")
    print("    net start LaylaSvc")
    print()
    print("  Then open: http://localhost:8000")
    print("  Layla will greet you with an onboarding interview.")
    print()

    return results


# ── CLI entry point ──────────────────────────────────────────────────────

if __name__ == "__main__":
    try:
        run_wizard()
    except KeyboardInterrupt:
        print("\n\n  Setup cancelled.\n")
        sys.exit(0)
