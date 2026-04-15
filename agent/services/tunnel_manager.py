"""
Manage an external tunnel process (e.g. cloudflared quick tunnel).

Requires ``cloudflared`` on PATH or path in config ``cloudflared_path``.
"""
from __future__ import annotations

import logging
import shutil
import subprocess
import threading
from typing import Any

logger = logging.getLogger("layla")

_proc: subprocess.Popen | None = None
_lock = threading.Lock()
_last_url: str = ""


def tunnel_status() -> dict[str, Any]:
    global _proc, _last_url
    alive = _proc is not None and _proc.poll() is None
    return {"running": alive, "url": _last_url or None}


def start_quick_tunnel(local_url: str = "http://127.0.0.1:8000", cloudflared: str | None = None) -> dict[str, Any]:
    """Start ``cloudflared tunnel --url <local_url>``; capture HTTPS URL from stderr (best effort)."""
    global _proc, _last_url
    exe = (cloudflared or "").strip() or shutil.which("cloudflared") or ""
    if not exe:
        return {"ok": False, "error": "cloudflared not found; install from https://developers.cloudflare.com/cloudflare-one/connections/connect-apps/install-and-setup/installation/"}
    with _lock:
        if _proc is not None and _proc.poll() is None:
            return {"ok": True, "running": True, "url": _last_url or None, "message": "already running"}
        try:
            _proc = subprocess.Popen(
                [exe, "tunnel", "--url", local_url],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                errors="replace",
            )
        except Exception as e:
            _proc = None
            return {"ok": False, "error": str(e)}

    def _watch() -> None:
        global _last_url
        if _proc is None or _proc.stderr is None:
            return
        try:
            for line in _proc.stderr:
                if "https://" in line and "trycloudflare.com" in line:
                    for part in line.split():
                        if part.startswith("https://"):
                            _last_url = part.strip().rstrip("|")
                            break
        except Exception as e:
            logger.debug("tunnel watch: %s", e)

    threading.Thread(target=_watch, daemon=True, name="cloudflared-watch").start()
    return {"ok": True, "running": True, "message": "started; URL will appear in /remote/tunnel/status when ready"}


def stop_tunnel() -> dict[str, Any]:
    global _proc, _last_url
    with _lock:
        if _proc is None:
            return {"ok": True, "stopped": False}
        try:
            _proc.terminate()
            try:
                _proc.wait(timeout=8)
            except Exception:
                _proc.kill()
        except Exception as e:
            return {"ok": False, "error": str(e)}
        finally:
            _proc = None
            _last_url = ""
    return {"ok": True, "stopped": True}
