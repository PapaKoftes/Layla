"""
Unified first-time setup runner.
Runs config wizard (setup_existing_model → installer_cli → first_run) with full error capture.
Then runs diagnose_startup to verify. Every error is captured and shown.
Run from repo root with venv activated: python agent/install/run_first_time.py
"""
from __future__ import annotations

import subprocess
import sys
import traceback
from pathlib import Path

# Ensure agent is on path
AGENT_DIR = Path(__file__).resolve().parent.parent
REPO_ROOT = AGENT_DIR.parent
for p in (str(AGENT_DIR), str(REPO_ROOT)):
    if p not in sys.path:
        sys.path.insert(0, p)


def _print_header():
    print()
    print("  ∴  Layla — First-Time Setup")
    print("  ─────────────────────────────────")
    print()


def _print_error(step: str, e: BaseException):
    """Show error clearly with full traceback."""
    print()
    print("  ┌" + "─" * 58 + "┐")
    print(f"  │  ERROR: {step}")
    print("  ├" + "─" * 58 + "┤")
    print(f"  │  {type(e).__name__}: {e}")
    print("  └" + "─" * 58 + "┘")
    print()
    print("  Full traceback:")
    traceback.print_exc()
    print()
    print("  See: knowledge/troubleshooting.md")
    print("  Or run: python agent/diagnose_startup.py")
    print()


def _run_config_wizard() -> bool:
    """Run config setup. Returns True if config is valid."""
    # 1. Try non-interactive (models exist)
    try:
        from install.setup_existing_model import run as setup_run
        if setup_run() == 0:
            return True
    except Exception as e:
        _print_error("setup_existing_model (auto-configure)", e)
        # Continue to interactive

    # 2. Try interactive installer
    try:
        from install.installer_cli import run as installer_run
        if installer_run() == 0:
            return True
    except EOFError:
        print("  [note] No input (non-interactive). Skipping installer.")
    except KeyboardInterrupt:
        print("  [note] Interrupted.")
    except Exception as e:
        _print_error("installer_cli (interactive wizard)", e)

    # 3. Try legacy first_run
    try:
        from first_run import run as first_run_fn
        if first_run_fn() == 0:
            return True
    except EOFError:
        print("  [note] No input. Skipping first_run.")
    except KeyboardInterrupt:
        print("  [note] Interrupted.")
    except Exception as e:
        _print_error("first_run (legacy wizard)", e)

    return False


def _run_diagnose() -> bool:
    """Run startup diagnostic. Returns True if all checks pass."""
    print()
    print("  Verifying installation...")
    print()
    try:
        r = subprocess.run(
            [sys.executable, str(AGENT_DIR / "diagnose_startup.py")],
            cwd=str(REPO_ROOT),
            capture_output=False,
        )
        return r.returncode == 0
    except Exception as e:
        _print_error("diagnose_startup", e)
        return False


def main() -> int:
    _print_header()

    config_ok = False
    try:
        config_ok = _run_config_wizard()
    except Exception as e:
        _print_error("config wizard", e)

    if not config_ok:
        print()
        print("  [note] Config not fully set. You can:")
        print("    • Run: python agent/install/installer_cli.py")
        print("    • Or:  python agent/first_run.py")
        print("    • Or edit agent/runtime_config.json manually (see MODELS.md)")
        print()

    # Always run diagnose to show full status
    diagnose_ok = _run_diagnose()

    print()
    if config_ok and diagnose_ok:
        print("  ═══════════════════════════════════════════════")
        print("   ✓  Setup complete. You're ready.")
        print("  ═══════════════════════════════════════════════")
        print()
        run_cmd = "START.bat" if sys.platform == "win32" else "bash start.sh"
        print(f"  Run  {run_cmd}")
        print("  Layla opens at:  http://localhost:8000/ui")
        print()
        return 0
    else:
        print("  ═══════════════════════════════════════════════")
        print("   Setup had issues. See above for details.")
        print("  ═══════════════════════════════════════════════")
        print()
        print("  Fix any [FAIL] items, then run START.bat or bash start.sh")
        print("  Diagnostic: python agent/diagnose_startup.py")
        print("  Troubleshooting: knowledge/troubleshooting.md")
        print()
        return 1


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\n  Interrupted.")
        sys.exit(130)
    except Exception as e:
        _print_error("run_first_time", e)
        sys.exit(1)
