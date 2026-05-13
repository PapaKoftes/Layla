"""
Tailscale mesh VPN tunnel backend for Layla remote access.

Alternative to cloudflared (tunnel_manager.py).  Uses the ``tailscale`` CLI
which works identically on Windows and Unix.

Config keys (from runtime_safety.py):
    tailscale_enabled  : bool  (default False)
    tailscale_auth_key : str   (optional, for headless auth via --authkey)
"""
from __future__ import annotations

import json
import logging
import shutil
import subprocess
from typing import Any

logger = logging.getLogger("layla")

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_TIMEOUT = 15  # seconds for every subprocess call


def _run(args: list[str], timeout: int = _TIMEOUT) -> subprocess.CompletedProcess[str]:
    """Run a command, returning the CompletedProcess result."""
    return subprocess.run(
        args,
        capture_output=True,
        text=True,
        timeout=timeout,
    )


def _tailscale_bin() -> str | None:
    """Return the path to the tailscale binary, or None."""
    return shutil.which("tailscale")


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def is_available() -> bool:
    """Return True if the ``tailscale`` binary is on PATH."""
    return _tailscale_bin() is not None


def get_status() -> dict[str, Any]:
    """Query ``tailscale status --json`` and return a normalised dict.

    Returns::

        {
            "running": bool,
            "ip": str | None,
            "hostname": str | None,
            "backend_state": str,
            "tailnet": str | None,
        }

    If tailscale is not installed or the command fails the dict will contain
    ``"running": False`` and an ``"error"`` key.
    """
    exe = _tailscale_bin()
    if exe is None:
        return {"running": False, "error": "tailscale binary not found on PATH"}

    try:
        result = _run([exe, "status", "--json"])
    except subprocess.TimeoutExpired:
        return {"running": False, "error": "tailscale status timed out"}
    except Exception as exc:
        return {"running": False, "error": str(exc)}

    if result.returncode != 0:
        # tailscale status exits non-zero when the daemon is stopped
        return {
            "running": False,
            "error": (result.stderr or result.stdout or "unknown error").strip(),
        }

    try:
        data = json.loads(result.stdout)
    except (json.JSONDecodeError, ValueError) as exc:
        return {"running": False, "error": f"failed to parse status JSON: {exc}"}

    backend_state = data.get("BackendState", "Unknown")
    running = backend_state == "Running"

    # Self node info
    self_node = data.get("Self", {})
    tailscale_ips = self_node.get("TailscaleIPs", [])
    ipv4 = None
    for ip in tailscale_ips:
        if "." in ip:  # simple IPv4 check
            ipv4 = ip
            break

    hostname = self_node.get("HostName")

    # Tailnet name lives under CurrentTailnet.Name (newer) or MagicDNSSuffix
    tailnet = None
    current_tailnet = data.get("CurrentTailnet", {})
    if isinstance(current_tailnet, dict):
        tailnet = current_tailnet.get("Name")
    if not tailnet:
        tailnet = data.get("MagicDNSSuffix") or None

    return {
        "running": running,
        "ip": ipv4,
        "hostname": hostname,
        "backend_state": backend_state,
        "tailnet": tailnet,
    }


def start_tailscale(cfg: dict[str, Any] | None = None) -> dict[str, Any]:
    """Bring the Tailscale connection up via ``tailscale up``.

    Parameters
    ----------
    cfg:
        Optional config dict.  Recognised keys:

        * ``tailscale_auth_key`` -- passed as ``--authkey`` for headless auth.

    Returns ``{"ok": bool, "message": str}``.
    """
    cfg = cfg or {}
    exe = _tailscale_bin()
    if exe is None:
        return {"ok": False, "message": "tailscale binary not found on PATH"}

    cmd: list[str] = [exe, "up"]
    auth_key = cfg.get("tailscale_auth_key", "").strip()
    if auth_key:
        cmd.extend(["--authkey", auth_key])

    try:
        result = _run(cmd)
    except subprocess.TimeoutExpired:
        return {"ok": False, "message": "tailscale up timed out"}
    except Exception as exc:
        logger.error("tailscale up failed: %s", exc)
        return {"ok": False, "message": str(exc)}

    if result.returncode != 0:
        msg = (result.stderr or result.stdout or "unknown error").strip()
        logger.warning("tailscale up returned %d: %s", result.returncode, msg)
        return {"ok": False, "message": msg}

    logger.info("tailscale up succeeded")
    return {"ok": True, "message": "tailscale is up"}


def stop_tailscale() -> dict[str, Any]:
    """Disconnect from the tailnet via ``tailscale down``.

    Returns ``{"ok": bool, "message": str}``.
    """
    exe = _tailscale_bin()
    if exe is None:
        return {"ok": False, "message": "tailscale binary not found on PATH"}

    try:
        result = _run([exe, "down"])
    except subprocess.TimeoutExpired:
        return {"ok": False, "message": "tailscale down timed out"}
    except Exception as exc:
        logger.error("tailscale down failed: %s", exc)
        return {"ok": False, "message": str(exc)}

    if result.returncode != 0:
        msg = (result.stderr or result.stdout or "unknown error").strip()
        logger.warning("tailscale down returned %d: %s", result.returncode, msg)
        return {"ok": False, "message": msg}

    logger.info("tailscale down succeeded")
    return {"ok": True, "message": "tailscale is down"}


def get_tailscale_ip() -> str | None:
    """Return the Tailscale IPv4 address, or None if unavailable."""
    exe = _tailscale_bin()
    if exe is None:
        return None

    try:
        result = _run([exe, "ip", "-4"])
    except Exception:
        return None

    if result.returncode != 0:
        return None

    ip = (result.stdout or "").strip().splitlines()
    return ip[0] if ip else None


def get_connection_url(port: int = 8000) -> str | None:
    """Return ``http://<tailscale_ip>:<port>`` if tailscale is running, else None."""
    ip = get_tailscale_ip()
    if ip is None:
        return None
    return f"http://{ip}:{port}"


def funnel_start(port: int = 8000) -> dict[str, Any]:
    """Start Tailscale Funnel to expose *port* publicly via HTTPS.

    Runs ``tailscale funnel <port>`` in a fire-and-forget manner.  The URL
    is derived from the machine's Tailscale hostname + tailnet domain.

    Returns ``{"ok": bool, "url": str | None, "message": str}``.
    """
    exe = _tailscale_bin()
    if exe is None:
        return {"ok": False, "url": None, "message": "tailscale binary not found on PATH"}

    try:
        result = _run([exe, "funnel", str(port)])
    except subprocess.TimeoutExpired:
        # Funnel may keep running; that is fine.  Treat timeout as success if
        # we can still get the status afterwards.
        pass
    except Exception as exc:
        logger.error("tailscale funnel start failed: %s", exc)
        return {"ok": False, "url": None, "message": str(exc)}
    else:
        if result.returncode != 0:
            msg = (result.stderr or result.stdout or "unknown error").strip()
            logger.warning("tailscale funnel returned %d: %s", result.returncode, msg)
            return {"ok": False, "url": None, "message": msg}

    # Derive public URL from status
    status = get_status()
    hostname = status.get("hostname")
    tailnet = status.get("tailnet")
    url: str | None = None
    if hostname and tailnet:
        url = f"https://{hostname}.{tailnet}"
    elif hostname:
        url = f"https://{hostname}"

    logger.info("tailscale funnel started on port %d -> %s", port, url or "(unknown)")
    return {"ok": True, "url": url, "message": f"funnel active on port {port}"}


def funnel_stop(port: int = 8000) -> dict[str, Any]:
    """Stop Tailscale Funnel for the given *port*.

    Runs ``tailscale funnel --off <port>``.

    Returns ``{"ok": bool, "message": str}``.
    """
    exe = _tailscale_bin()
    if exe is None:
        return {"ok": False, "message": "tailscale binary not found on PATH"}

    try:
        result = _run([exe, "funnel", "--off", str(port)])
    except subprocess.TimeoutExpired:
        return {"ok": False, "message": "tailscale funnel --off timed out"}
    except Exception as exc:
        logger.error("tailscale funnel stop failed: %s", exc)
        return {"ok": False, "message": str(exc)}

    if result.returncode != 0:
        msg = (result.stderr or result.stdout or "unknown error").strip()
        logger.warning("tailscale funnel --off returned %d: %s", result.returncode, msg)
        return {"ok": False, "message": msg}

    logger.info("tailscale funnel stopped on port %d", port)
    return {"ok": True, "message": f"funnel stopped on port {port}"}
