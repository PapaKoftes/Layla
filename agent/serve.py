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
  LAYLA_RELOAD  "0" to disable uvicorn --reload (default on)
  LAYLA_NO_BROWSER  "1" to not auto-open the browser
"""
from __future__ import annotations

import os
import sys
import threading
import time
import webbrowser


def _load_port(default: int = 8000) -> int:
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


def main() -> int:
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

    reload_enabled = (os.environ.get("LAYLA_RELOAD", "1") or "1").strip().lower() not in ("0", "false", "no")
    _open_browser_soon(f"http://{host}:{serve_port}/ui")
    uvicorn.run("main:app", host=host, port=serve_port, reload=reload_enabled)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
