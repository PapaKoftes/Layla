"""
Layla thin bootstrapper — the *frozen* entrypoint (this is what ``layla.exe`` runs).

Why this exists: before 1.8.0 the whole launcher was compiled into ``layla.exe``, so a one-line launcher
bug (see the 1.7.5 boot crash) could only be fixed by re-shipping the 410 MB installer. This bootstrapper
is deliberately tiny and stable: all it does is find the *external, updatable* launcher script and run it
with the bundled Python. Fixing or updating the launcher then means replacing a plain ``.py`` file — which
the in-app updater and the Repair tool can both do, with no reinstall.

Resolution (first that exists wins) — the override dir lives under the per-user data dir, so updates never
need admin and the installed copy under Program Files stays pristine:

    launcher script:  <data>/app_override/launcher/layla_launcher.py   (updated)
                      <install>/launcher/layla_launcher.py             (shipped)
    python:           <install>/python/python.exe                     (bundled embeddable)
                      the current interpreter (running from source)

Crash-proof by construction: like the launcher's own _fatal, this never writes to a possibly-None stderr,
always records a log, and shows a MessageBox so a packaged (console=False) failure is visible instead of
silent. It points the user at "Repair Layla".
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


def _data_dir() -> Path:
    d = (os.environ.get("LAYLA_DATA_DIR") or "").strip()
    if not d:
        if sys.platform == "win32" and os.environ.get("LOCALAPPDATA"):
            d = str(Path(os.environ["LOCALAPPDATA"]) / "Layla")
        else:
            d = str(Path.home() / ".local" / "share" / "Layla")
    return Path(d).expanduser()


def _install_root() -> Path:
    raw = (os.environ.get("LAYLA_INSTALL_ROOT") or "").strip()
    if raw:
        return Path(raw).expanduser().resolve()
    # Frozen: the exe sits at the install root. From source: launcher/ -> repo root.
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


def _launch_log(data: Path) -> Path:
    return data / "logs" / "boot.log"


def _fatal(title: str, message: str, data: Path) -> None:
    """Show a boot failure without ever raising (stderr is None in the packaged exe)."""
    try:
        if sys.stderr is not None:
            sys.stderr.write(message + "\n")
    except Exception:
        pass
    log: Path | None = _launch_log(data)
    try:
        log.parent.mkdir(parents=True, exist_ok=True)
        with log.open("a", encoding="utf-8") as fh:
            fh.write(message + "\n")
    except OSError:
        log = None
    if sys.platform == "win32" and (os.environ.get("LAYLA_NO_DIALOG", "") or "").strip().lower() not in ("1", "true", "yes", "on"):
        try:
            import ctypes

            hint = f"\n\nA log was saved to:\n{log}" if log else ""
            hint += "\n\nTry 'Repair Layla' from the Start menu."
            ctypes.windll.user32.MessageBoxW(None, message + hint, title, 0x10)  # MB_ICONERROR
        except Exception:
            pass


def _resolve_launcher(install_root: Path, data: Path) -> Path | None:
    for cand in (
        data / "app_override" / "launcher" / "layla_launcher.py",   # updated
        install_root / "launcher" / "layla_launcher.py",            # shipped
    ):
        if cand.is_file():
            return cand
    return None


def _resolve_python(install_root: Path) -> Path | None:
    embedded = install_root / "python" / "python.exe"
    if embedded.is_file():
        return embedded
    # Running from source: use the current interpreter — but never the frozen exe itself.
    if getattr(sys, "frozen", False):
        return None
    return Path(sys.executable).resolve()


def main() -> int:
    data = _data_dir()
    install_root = _install_root()
    os.environ.setdefault("LAYLA_INSTALL_ROOT", str(install_root))

    launcher = _resolve_launcher(install_root, data)
    if launcher is None:
        _fatal(
            "Layla is incomplete",
            "Layla's launcher script was not found under:\n"
            f"  {data / 'app_override' / 'launcher'}\n  {install_root / 'launcher'}\n\n"
            "The install may be damaged — please reinstall or run Repair.",
            data,
        )
        return 2
    py = _resolve_python(install_root)
    if py is None:
        _fatal(
            "Layla runtime missing",
            f"Layla's bundled Python was not found:\n{install_root / 'python' / 'python.exe'}\n\n"
            "The install is incomplete — please reinstall Layla.",
            data,
        )
        return 2

    # Hand off to the external launcher, forwarding our args. It owns health-wait, tray, and browser.
    cmd = [str(py), str(launcher), *sys.argv[1:]]
    try:
        return subprocess.call(cmd, cwd=str(launcher.parent))
    except Exception as exc:  # noqa: BLE001 — last resort, must not crash silently
        _fatal("Layla failed to start", f"Could not start the Layla launcher:\n\n{exc!r}", data)
        return 1


if __name__ == "__main__":
    try:
        _rc = main()
    except SystemExit:
        raise
    except BaseException as _exc:  # noqa: BLE001 — show *something* before exit
        _fatal("Layla failed to start", f"Unexpected error during boot:\n\n{_exc!r}", _data_dir())
        _rc = 1
    raise SystemExit(_rc)
