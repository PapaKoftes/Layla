"""
Layla desktop launcher: start uvicorn when needed, wait for /health, open the Web UI.

Packaged layout (Windows)::

 C:\\Program Files\\Layla\\
      layla.exe          # this entrypoint built with PyInstaller
      python\\python.exe # optional embedded runtime
      agent\\ # application tree

Environment (set by installer or here)::

    LAYLA_INSTALL_ROOT  - directory containing ``agent/`` (default: parent of this script / exe)
    LAYLA_DATA_DIR      - per-user data: runtime_config.json, layla.db, models/, …

Optional tray menu requires ``pystray`` and ``pillow``; otherwise the process blocks until Ctrl+C.
"""
from __future__ import annotations

import argparse
import atexit
import os
import shutil
import signal
import subprocess
import sys
import threading
import time
import webbrowser
from pathlib import Path
from urllib.error import URLError
from urllib.request import urlopen

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8000
HOST = DEFAULT_HOST
PORT = DEFAULT_PORT
HEALTH_URL = f"http://{HOST}:{PORT}/health"
UI_URL = f"http://{HOST}:{PORT}/ui"


def _launch_log_path() -> Path:
    base = (os.environ.get("LAYLA_DATA_DIR") or "").strip() or str(Path.home())
    return Path(base) / "logs" / "launch.log"


def _fatal(title: str, message: str) -> None:
    """Surface a fatal startup error to the user.

    ``layla.exe`` is built windowed (``console=False``), so anything written to
    stderr is invisible — a boot failure would otherwise look like nothing
    happened. Append the message to launch.log and, on Windows, pop a MessageBox
    so the user actually sees why Layla didn't start. Never raises.
    Set ``LAYLA_NO_DIALOG=1`` to suppress the popup (used by automated tests).
    """
    # ``console=False`` means sys.stderr is None in the packaged exe — writing to it raises
    # AttributeError and, because _fatal IS the error handler, that used to double-fault and hide the
    # real cause (plus skip the log + MessageBox below). Guard every side effect so _fatal cannot raise.
    try:
        if sys.stderr is not None:
            sys.stderr.write(message + "\n")
    except Exception:
        pass
    log: Path | None = _launch_log_path()
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
            ctypes.windll.user32.MessageBoxW(None, message + hint, title, 0x10)  # MB_ICONERROR
        except Exception:
            pass


def _resolve_install_root() -> Path:
    raw = (os.environ.get("LAYLA_INSTALL_ROOT") or "").strip()
    if raw:
        return Path(raw).expanduser().resolve()
    # Running from source: launcher/ -> repo root
    here = Path(__file__).resolve().parent
    if (here.parent / "agent" / "main.py").is_file():
        return here.parent
    # PyInstaller onefile extracts to _MEIPASS; fall back to directory of executable
    me = getattr(sys, "_MEIPASS", None)
    if me:
        p = Path(me)
        if (p / "agent" / "main.py").is_file():
            return p
    return Path(sys.executable).resolve().parent


def _ensure_data_dir() -> Path:
    if not (os.environ.get("LAYLA_DATA_DIR") or "").strip():
        if sys.platform == "win32":
            la = os.environ.get("LOCALAPPDATA", "")
            if la:
                os.environ["LAYLA_DATA_DIR"] = str(Path(la) / "Layla")
        if not (os.environ.get("LAYLA_DATA_DIR") or "").strip():
            os.environ["LAYLA_DATA_DIR"] = str(Path.home() / ".local" / "share" / "Layla")
    data = Path(os.environ["LAYLA_DATA_DIR"]).expanduser().resolve()
    data.mkdir(parents=True, exist_ok=True)
    return data


def _seed_runtime_config(install_root: Path, data: Path) -> None:
    cfg = data / "runtime_config.json"
    if cfg.is_file():
        return
    for ex in (install_root / "runtime_config.example.json", install_root / "agent" / "runtime_config.example.json"):
        if ex.is_file():
            try:
                shutil.copy2(ex, cfg)
                return
            except OSError:
                pass


def _pick_python(install_root: Path) -> Path | None:
    """Interpreter to run the engine with. Prefer the bundled embedded Python; else the current
    interpreter — but NEVER the frozen launcher exe itself (``layla.exe -c ...`` would just re-run the
    launcher and exit, which is the classic "engine died before health" boot failure). Returns None when
    no real interpreter is available so the caller can report a clear "reinstall" error."""
    embedded = install_root / "python" / "python.exe"
    if embedded.is_file():
        return embedded
    if getattr(sys, "frozen", False):
        return None
    return Path(sys.executable).resolve()


def _health_ok() -> bool:
    # Uses global HEALTH_URL, set in main() after arg parsing.
    try:
        with urlopen(HEALTH_URL, timeout=2) as r:
            return r.status == 200
    except (URLError, OSError, TimeoutError):
        return False


def _open_ui() -> None:
    # Uses global UI_URL, set in main() after arg parsing.
    webbrowser.open(UI_URL)


def main() -> int:
    parser = argparse.ArgumentParser(prog="layla", add_help=True)
    parser.add_argument("--host", default=DEFAULT_HOST, help="Bind host (default: 127.0.0.1)")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT, help="Bind port (default: 8000)")
    parser.add_argument("--no-tray", action="store_true", help="Disable system tray icon even if deps exist")
    args = parser.parse_args()

    global HEALTH_URL, UI_URL, HOST, PORT  # noqa: PLW0603 - simple launcher globals
    HOST = str(args.host or DEFAULT_HOST)
    PORT = int(args.port or DEFAULT_PORT)
    HEALTH_URL = f"http://{HOST}:{PORT}/health"
    UI_URL = f"http://{HOST}:{PORT}/ui"

    install_root = _resolve_install_root()
    os.environ.setdefault("LAYLA_INSTALL_ROOT", str(install_root))
    data_dir = _ensure_data_dir()
    _seed_runtime_config(install_root, data_dir)

    agent_dir = install_root / "agent"
    if not agent_dir.is_dir():
        _fatal(
            "Layla files missing",
            f"Layla application files were not found here:\n{agent_dir}\n\n"
            "The install may be incomplete — try reinstalling Layla.",
        )
        return 2

    os.chdir(str(agent_dir))
    env = os.environ.copy()
    pp = env.get("PYTHONPATH", "")
    agent_s = str(agent_dir)
    env["PYTHONPATH"] = agent_s if not pp else agent_s + os.pathsep + pp

    if _health_ok():
        _open_ui()
        return 0

    py = _pick_python(install_root)
    if py is None:
        _fatal(
            "Layla runtime missing",
            "Layla's bundled Python runtime was not found next to the app:\n"
            f"{install_root / 'python' / 'python.exe'}\n\n"
            "The install is incomplete — please reinstall Layla.",
        )
        return 2
    # Start uvicorn via an explicit sys.path bootstrap instead of `-m uvicorn`. The bundled *embeddable*
    # Python ignores PYTHONPATH (a python*._pth file puts it in isolated mode), so `main:app` would be
    # unimportable there; inserting agent_dir into sys.path in-process is honored by every interpreter.
    # Values pass through the environment (not string-formatted into the code) so a path with quotes or
    # trailing backslashes can never break the bootstrap.
    env["LAYLA_ENGINE_AGENT_DIR"] = str(agent_dir)
    env["LAYLA_ENGINE_HOST"] = HOST
    env["LAYLA_ENGINE_PORT"] = str(PORT)
    _boot = (
        "import os, sys; sys.path.insert(0, os.environ['LAYLA_ENGINE_AGENT_DIR']); "
        "import uvicorn; uvicorn.run('main:app', host=os.environ['LAYLA_ENGINE_HOST'], "
        "port=int(os.environ['LAYLA_ENGINE_PORT']))"
    )
    cmd = [str(py), "-c", _boot]
    proc: subprocess.Popen | None = None

    def _terminate_proc() -> None:
        if proc is not None and proc.poll() is None:
            try:
                proc.terminate()
            except OSError:
                pass

    # Tee the server's own output to launch.log so a boot failure has a readable
    # cause (this exe is windowed, so the child's stderr would otherwise vanish).
    log_path = _launch_log_path()
    try:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        _log_fh = log_path.open("w", encoding="utf-8")
    except OSError:
        _log_fh = None
    proc = subprocess.Popen(
        cmd, cwd=str(agent_dir), env=env,
        stdout=_log_fh, stderr=subprocess.STDOUT if _log_fh else None,
    )
    atexit.register(_terminate_proc)

    def _on_signal(_signum: int, _frame: object | None) -> None:
        _terminate_proc()
        raise SystemExit(0)

    for _sig in (getattr(signal, "SIGTERM", None), getattr(signal, "SIGINT", None)):
        if _sig is not None:
            try:
                signal.signal(_sig, _on_signal)
            except OSError:
                pass

    try:
        for _ in range(180):
            time.sleep(0.5)
            if _health_ok():
                break
            if proc.poll() is not None:
                _fatal(
                    "Layla could not start",
                    "Layla's engine stopped before it finished starting.\n"
                    "The saved log has the exact error (often: a missing model, "
                    "a blocked port, or a dependency that failed to load).",
                )
                return 1
        else:
            proc.terminate()
            _fatal(
                "Layla is taking too long",
                "Layla started but did not become ready in time.\n"
                "Try launching it again; the saved log has the details.",
            )
            return 1

        _open_ui()

        def _tray() -> bool:
            if args.no_tray:
                return False
            try:
                import pystray
                from PIL import Image
            except Exception:
                return False
            image = Image.new("RGB", (64, 64), color=(90, 20, 70))

            def open_ui(_icon, _item):
                _open_ui()

            def quit_app(icon, _item):
                _terminate_proc()
                icon.stop()

            menu = pystray.Menu(
                pystray.MenuItem("Open Layla", open_ui),
                pystray.MenuItem("Quit", quit_app),
            )
            icon = pystray.Icon("layla", image, "Layla", menu)
            threading.Thread(target=icon.run, daemon=True).start()
            return True

        if _tray():
            try:
                proc.wait()
            except KeyboardInterrupt:
                _terminate_proc()
        else:
            try:
                proc.wait()
            except KeyboardInterrupt:
                _terminate_proc()
        return 0
    finally:
        _terminate_proc()


if __name__ == "__main__":
    try:
        _rc = main()
    except SystemExit:
        raise
    except BaseException:  # noqa: BLE001 - last-resort: show *something* before exit
        import traceback

        _fatal(
            "Layla failed to start",
            "Layla hit an unexpected error while starting:\n\n" + traceback.format_exc(),
        )
        _rc = 1
    raise SystemExit(_rc)
