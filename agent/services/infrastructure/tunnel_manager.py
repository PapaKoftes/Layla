"""
Manage an external tunnel process (e.g. cloudflared quick tunnel).

Requires ``cloudflared`` on PATH or path in config ``cloudflared_path``.

Phase 5 additions: ``health_check()`` for probing the active tunnel URL,
``_consecutive_failures`` counter, and ``auto_restart_if_unhealthy()`` that
restarts the tunnel after N consecutive probe failures.
"""
from __future__ import annotations

import logging
import shutil
import subprocess
import threading
import time
from typing import Any

logger = logging.getLogger("layla")

_proc: subprocess.Popen | None = None
_lock = threading.Lock()
_last_url: str = ""

# Health-check state
_consecutive_failures: int = 0
_MAX_FAILURES_BEFORE_RESTART: int = 3
_last_health_check: float = 0.0
_last_local_url: str = "http://127.0.0.1:8000"


def tunnel_status() -> dict[str, Any]:
    global _proc, _last_url
    alive = _proc is not None and _proc.poll() is None
    return {"running": alive, "url": _last_url or None}


def start_quick_tunnel(local_url: str = "http://127.0.0.1:8000", cloudflared: str | None = None) -> dict[str, Any]:
    """Start ``cloudflared tunnel --url <local_url>``; capture HTTPS URL from stderr (best effort)."""
    global _proc, _last_url, _last_local_url, _consecutive_failures
    _last_local_url = local_url
    _consecutive_failures = 0
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
    global _proc, _last_url, _consecutive_failures
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
            _consecutive_failures = 0
    return {"ok": True, "stopped": True}


# ---------------------------------------------------------------------------
# Health check + auto-restart (Phase 5)
# ---------------------------------------------------------------------------

def health_check(timeout: int = 10) -> dict[str, Any]:
    """Probe the active tunnel URL with a HEAD request.

    Returns ``{"healthy": True/False, "url": ..., "latency_ms": ..., ...}``.
    Also updates the internal ``_consecutive_failures`` counter.
    """
    global _consecutive_failures, _last_health_check

    status = tunnel_status()
    if not status["running"]:
        return {"healthy": False, "reason": "tunnel_not_running", "url": None}

    url = status.get("url")
    if not url:
        return {"healthy": False, "reason": "no_tunnel_url", "url": None}

    with _lock:
        _last_health_check = time.time()
    try:
        import urllib.request
        start = time.monotonic()
        req = urllib.request.Request(url, method="HEAD")
        resp = urllib.request.urlopen(req, timeout=timeout)
        latency_ms = round((time.monotonic() - start) * 1000)
        with _lock:
            _consecutive_failures = 0
        return {
            "healthy": True,
            "url": url,
            "status_code": resp.status,
            "latency_ms": latency_ms,
            "consecutive_failures": 0,
        }
    except Exception as e:
        with _lock:
            _consecutive_failures += 1
            _cf = _consecutive_failures
        return {
            "healthy": False,
            "url": url,
            "reason": str(e),
            "consecutive_failures": _cf,
        }


def get_health_state() -> dict[str, Any]:
    """Return the current health state without probing."""
    return {
        "consecutive_failures": _consecutive_failures,
        "max_failures_before_restart": _MAX_FAILURES_BEFORE_RESTART,
        "last_health_check": _last_health_check,
        "last_local_url": _last_local_url,
    }


def auto_restart_if_unhealthy(
    local_url: str = "",
    cloudflared: str | None = None,
    max_failures: int | None = None,
) -> dict[str, Any]:
    """Check health; if consecutive failures exceed threshold, restart the tunnel.

    Returns the health check result, plus ``{"restarted": True}`` if a restart
    was triggered.
    """
    global _consecutive_failures

    threshold = max_failures or _MAX_FAILURES_BEFORE_RESTART
    hc = health_check()

    if hc.get("healthy"):
        return {**hc, "restarted": False}

    with _lock:
        _cf = _consecutive_failures
    if _cf < threshold:
        return {
            **hc,
            "restarted": False,
            "message": f"unhealthy ({_cf}/{threshold} failures)",
        }

    # Restart
    logger.warning(
        "tunnel auto-restart: %d consecutive failures (threshold=%d), restarting",
        _cf, threshold,
    )
    stop_tunnel()
    _lu = (local_url or _last_local_url or "http://127.0.0.1:8000").strip()
    start_result = start_quick_tunnel(local_url=_lu, cloudflared=cloudflared)
    return {
        **hc,
        "restarted": True,
        "restart_result": start_result,
    }
