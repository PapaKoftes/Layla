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

HOST = "127.0.0.1"
PORT = 8000
HEALTH_URL = f"http://{HOST}:{PORT}/health"
UI_URL = f"http://{HOST}:{PORT}/ui"


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


def _pick_python(install_root: Path) -> Path:
    embedded = install_root / "python" / "python.exe"
    if embedded.is_file():
        return embedded
    return Path(sys.executable).resolve()


def _health_ok() -> bool:
    try:
        with urlopen(HEALTH_URL, timeout=2) as r:
            return r.status == 200
    except (URLError, OSError, TimeoutError):
        return False


def _open_ui() -> None:
    webbrowser.open(UI_URL)


def main() -> int:
    install_root = _resolve_install_root()
    os.environ.setdefault("LAYLA_INSTALL_ROOT", str(install_root))
    data_dir = _ensure_data_dir()
    _seed_runtime_config(install_root, data_dir)

    agent_dir = install_root / "agent"
    if not agent_dir.is_dir():
        sys.stderr.write(f"Layla agent directory not found: {agent_dir}\n")
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
    cmd = [str(py), "-m", "uvicorn", "main:app", "--host", HOST, "--port", str(PORT)]
    proc: subprocess.Popen | None = None

    def _terminate_proc() -> None:
        if proc is not None and proc.poll() is None:
            try:
                proc.terminate()
            except OSError:
                pass

    proc = subprocess.Popen(cmd, cwd=str(agent_dir), env=env)
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
                sys.stderr.write("Layla server exited before /health was ready.\n")
                return 1
        else:
            proc.terminate()
            sys.stderr.write("Timed out waiting for Layla /health.\n")
            return 1

        _open_ui()

        def _tray() -> bool:
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
    raise SystemExit(main())
