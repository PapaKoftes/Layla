#!/usr/bin/env python3
"""Layla server entrypoint with a port-conflict guard.

Run from the agent/ directory:  python serve.py

Unlike calling `uvicorn main:app --port 8000` directly, this first checks the
port so Layla never collides silently with another program:
  - free            -> start normally
  - already Layla    -> open the browser at the running instance, don't double-start
  - foreign program  -> relocate to the next free port (and report it)
  - nothing free     -> exit with a clear message

Env:
  LAYLA_HOST    bind host (default 127.0.0.1)
  LAYLA_RELOAD  "1" to enable uvicorn --reload for development (default OFF)
  LAYLA_NO_BROWSER  "1" to not auto-open the browser
"""
from __future__ import annotations

import os
import sys
import threading
import time
import webbrowser


def _load_port(default: int = 8000) -> int:
    # --port / LAYLA_PORT wins over runtime_config.json.
    _env = (os.environ.get("LAYLA_PORT") or "").strip()
    if _env:
        try:
            return int(_env)
        except ValueError:
            pass
    try:
        import runtime_safety

        cfg = runtime_safety.load_config()
        return int(cfg.get("port", default) or default)
    except Exception:
        return default


def _truthy(name: str, default: str = "0") -> bool:
    return (os.environ.get(name, default) or "").strip().lower() in ("1", "true", "yes", "on")


def _open_browser_soon(url: str, delay: float = 2.5) -> None:
    if _truthy("LAYLA_NO_BROWSER"):
        return

    def _go() -> None:
        time.sleep(delay)
        try:
            webbrowser.open(url)
        except Exception:
            pass

    threading.Thread(target=_go, daemon=True).start()


def _parse_args(argv=None) -> None:
    """Parse CLI flags into the env vars main() already reads (so `layla --help` works
    while the LAYLA_* env-var interface stays fully backward-compatible)."""
    import argparse

    p = argparse.ArgumentParser(
        prog="layla",
        description="Start the Layla server (local-first AI companion). Opens the Web UI at /ui.",
        epilog="All flags have LAYLA_* env-var equivalents (LAYLA_HOST, LAYLA_PORT, LAYLA_NO_BROWSER, LAYLA_RELOAD).",
    )
    p.add_argument("--host", metavar="ADDR", help="Bind address (default 127.0.0.1; env LAYLA_HOST).")
    p.add_argument("--port", type=int, metavar="N", help="Port (default 8000 / runtime_config.json; env LAYLA_PORT).")
    p.add_argument("--no-browser", action="store_true", help="Do not auto-open the browser (env LAYLA_NO_BROWSER=1).")
    p.add_argument("--reload", action="store_true", help="Dev auto-reload (env LAYLA_RELOAD=1). Not for production.")
    try:
        from version import __version__ as _v
    except Exception:
        _v = "?"
    p.add_argument("--version", action="version", version=f"Layla {_v}")
    a = p.parse_args(argv)
    if a.host:
        os.environ["LAYLA_HOST"] = a.host
    if a.port is not None:
        os.environ["LAYLA_PORT"] = str(a.port)
    if a.no_browser:
        os.environ["LAYLA_NO_BROWSER"] = "1"
    if a.reload:
        os.environ["LAYLA_RELOAD"] = "1"


def main() -> int:
    _parse_args()
    host = os.environ.get("LAYLA_HOST", "127.0.0.1").strip() or "127.0.0.1"
    port = _load_port()

    import port_guard

    decision = port_guard.resolve_serve_port(host, port)
    print(f"[Layla] {decision['message']}")

    action = decision["action"]
    if action == "already_running":
        if not _truthy("LAYLA_NO_BROWSER"):
            try:
                webbrowser.open(f"http://{host}:{decision['port']}/ui")
            except Exception:
                pass
        return 0
    if action == "blocked":
        return 2

    serve_port = int(decision["port"])  # "start" or "relocated"
    try:
        import uvicorn
    except Exception as exc:  # pragma: no cover - environment dependent
        print(f"[Layla] uvicorn is not installed: {exc}", file=sys.stderr)
        return 1

    # Production default: reload OFF. --reload watches the whole tree, thrashes on
    # Windows, and restarts the server (dropping the loaded model + in-flight runs)
    # on any file write. Opt in for development with LAYLA_RELOAD=1.
    reload_enabled = (os.environ.get("LAYLA_RELOAD", "0") or "0").strip().lower() in ("1", "true", "yes", "on")
    _open_browser_soon(f"http://{host}:{serve_port}/ui")
    uvicorn.run("main:app", host=host, port=serve_port, reload=reload_enabled)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
