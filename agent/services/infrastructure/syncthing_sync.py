"""
syncthing_sync.py — Multi-device sync orchestration via Syncthing REST API.

Layla uses this service to:
  1. Check whether a local Syncthing daemon is running.
  2. Discover peer devices sharing the same folder.
  3. Trigger rescan/sync of the Layla data directory.
  4. Report sync status (up-to-date, syncing, out-of-sync).

Syncthing must be installed separately:
  https://syncthing.net/downloads/

The API key lives in config.json → "syncthing_api_key".
The GUI/REST base URL defaults to http://127.0.0.1:8384 (Syncthing default).
The folder ID defaults to "layla-data" (user must configure this in Syncthing).

None of this is required — if Syncthing is not running or not configured,
every call gracefully returns a disabled/unavailable status dict.

Security: the API key is NEVER logged; it is read from config at call time.
"""
from __future__ import annotations

import json
import logging
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_DEFAULT_BASE_URL = "http://127.0.0.1:8384"
_TIMEOUT_S = 5  # seconds for each REST call


# ── Helpers ───────────────────────────────────────────────────────────────────

def _get_config() -> dict:
    """Load agent config.json lazily (delegates to services.config_cache)."""
    try:
        from services.config_cache import get_config
        return get_config()
    except Exception:
        return {}


def _api_key() -> str:
    return _get_config().get("syncthing_api_key", "")


def _base_url() -> str:
    return _get_config().get("syncthing_base_url", _DEFAULT_BASE_URL).rstrip("/")


def _folder_id() -> str:
    return _get_config().get("syncthing_folder_id", "layla-data")


def _request(method: str, path: str, body: dict | None = None) -> tuple[int, Any]:
    """
    Make a Syncthing REST call.
    Returns (http_status_code, parsed_json_or_None).
    Never raises — callers check the status code.
    """
    key = _api_key()
    if not key:
        return 0, None  # Not configured

    url = _base_url() + path
    data = json.dumps(body).encode() if body else None
    headers = {
        "X-API-Key": key,
        "Content-Type": "application/json",
        "Accept": "application/json",
    }
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=_TIMEOUT_S) as resp:
            status = resp.status
            try:
                payload = json.loads(resp.read())
            except Exception:
                payload = None
            return status, payload
    except urllib.error.HTTPError as exc:
        return exc.code, None
    except Exception as exc:
        logger.debug("syncthing_sync: request failed (%s %s): %s", method, path, exc)
        return 0, None


# ── Public API ────────────────────────────────────────────────────────────────

def is_running() -> bool:
    """Return True if a Syncthing daemon is reachable at the configured URL."""
    status, _ = _request("GET", "/rest/system/ping")
    return status == 200


def get_status() -> dict:
    """
    Return a status dict suitable for the /sync/status endpoint.

    Keys:
      enabled      bool   — syncthing_api_key is set in config
      running      bool   — daemon is reachable
      folder_id    str
      folder_state str    — "idle" | "syncing" | "error" | "unknown"
      completion   float  — 0.0–100.0 (own completion for the folder)
      devices      list   — [{device_id, name, connected, completion}]
      error        str|None
    """
    enabled = bool(_api_key())
    if not enabled:
        return {
            "enabled": False,
            "running": False,
            "folder_id": _folder_id(),
            "folder_state": "unknown",
            "completion": 0.0,
            "devices": [],
            "error": "syncthing_api_key not set in config.json",
        }

    if not is_running():
        return {
            "enabled": True,
            "running": False,
            "folder_id": _folder_id(),
            "folder_state": "unknown",
            "completion": 0.0,
            "devices": [],
            "error": "Syncthing daemon not reachable",
        }

    folder_id = _folder_id()
    folder_state = "unknown"
    completion_pct = 0.0
    error_msg: str | None = None

    # Folder status
    status_code, folder_info = _request("GET", f"/rest/db/status?folder={folder_id}")
    if status_code == 200 and folder_info:
        folder_state = folder_info.get("state", "unknown")
    elif status_code == 404:
        error_msg = f"Folder '{folder_id}' not found in Syncthing — add it via the Syncthing GUI."

    # Own completion
    comp_code, comp_info = _request("GET", f"/rest/db/completion?folder={folder_id}")
    if comp_code == 200 and comp_info:
        completion_pct = float(comp_info.get("completion", 0.0))

    # Devices
    devices: list[dict] = []
    cfg_code, cfg_info = _request("GET", "/rest/config")
    if cfg_code == 200 and cfg_info:
        configured_devices = cfg_info.get("devices", [])
        # Get connection status
        conn_code, conns = _request("GET", "/rest/system/connections")
        conn_map: dict[str, dict] = {}
        if conn_code == 200 and conns:
            conn_map = conns.get("connections", {})

        # Per-device completion for this folder
        for dev in configured_devices:
            dev_id = dev.get("deviceID", "")
            dev_name = (dev.get("name") or dev_id[:8])
            connected = conn_map.get(dev_id, {}).get("connected", False)
            dev_comp = 0.0
            dc_code, dc_info = _request(
                "GET", f"/rest/db/completion?folder={folder_id}&device={dev_id}"
            )
            if dc_code == 200 and dc_info:
                dev_comp = float(dc_info.get("completion", 0.0))
            devices.append({
                "device_id": dev_id,
                "name": dev_name,
                "connected": connected,
                "completion": dev_comp,
            })

    return {
        "enabled": True,
        "running": True,
        "folder_id": folder_id,
        "folder_state": folder_state,
        "completion": completion_pct,
        "devices": devices,
        "error": error_msg,
    }


def trigger_rescan() -> dict:
    """
    Ask Syncthing to rescan the Layla folder immediately.
    Returns {"ok": True} on success, {"ok": False, "error": "..."} on failure.
    """
    if not is_running():
        return {"ok": False, "error": "Syncthing not running"}
    folder_id = _folder_id()
    code, _ = _request("POST", f"/rest/db/scan?folder={folder_id}")
    if code == 200:
        logger.info("syncthing_sync: rescan triggered for folder '%s'", folder_id)
        return {"ok": True}
    return {"ok": False, "error": f"Syncthing returned HTTP {code}"}


def get_device_id() -> str | None:
    """Return this device's own Syncthing device ID, or None if unavailable."""
    code, info = _request("GET", "/rest/system/status")
    if code == 200 and info:
        return info.get("myID")
    return None


def add_device(device_id: str, name: str = "", auto_accept: bool = True) -> dict:
    """
    Add a peer device to Syncthing config and share the Layla folder with it.
    This patches the Syncthing config via REST.
    Returns {"ok": True} or {"ok": False, "error": "..."}.
    """
    if not is_running():
        return {"ok": False, "error": "Syncthing not running"}

    # Load current config
    cfg_code, cfg = _request("GET", "/rest/config")
    if cfg_code != 200 or not cfg:
        return {"ok": False, "error": "Could not load Syncthing config"}

    # Check if device already present
    existing_ids = {d.get("deviceID") for d in cfg.get("devices", [])}
    if device_id not in existing_ids:
        new_device = {
            "deviceID": device_id,
            "name": name or device_id[:8],
            "addresses": ["dynamic"],
            "compression": "metadata",
            "introducer": False,
            "autoAcceptFolders": auto_accept,
        }
        cfg["devices"].append(new_device)

    # Add device to the layla-data folder's sharedWith list
    folder_id = _folder_id()
    for folder in cfg.get("folders", []):
        if folder.get("id") == folder_id:
            shared_ids = {d.get("deviceID") for d in folder.get("devices", [])}
            if device_id not in shared_ids:
                folder["devices"].append({"deviceID": device_id, "introducedBy": ""})
            break

    # Push updated config
    put_code, _ = _request("PUT", "/rest/config", body=cfg)
    if put_code in (200, 204):
        logger.info("syncthing_sync: added device %s ('%s') and shared folder '%s'",
                    device_id, name, folder_id)
        return {"ok": True}
    return {"ok": False, "error": f"Config update returned HTTP {put_code}"}
