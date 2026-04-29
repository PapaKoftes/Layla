"""
sync.py — Multi-device sync endpoints (Syncthing integration).

Endpoints:
  GET  /sync/status          — Current sync state, folder health, peer devices
  POST /sync/rescan          — Trigger immediate folder rescan
  GET  /sync/device-id       — Return this device's Syncthing ID (for pairing)
  POST /sync/add-device      — Add a peer device and share the Layla folder
  GET  /sync/setup-guide     — Human-readable setup instructions

All endpoints are safe to call even if Syncthing is not installed; they
return {"enabled": false, ...} rather than erroring.

Configuration keys in config.json:
  syncthing_api_key     string   — Syncthing REST API key (required to enable)
  syncthing_base_url    string   — Default: http://127.0.0.1:8384
  syncthing_folder_id   string   — Default: "layla-data"
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from services import syncthing_sync

router = APIRouter(prefix="/sync", tags=["sync"])


# ── Response / request models ─────────────────────────────────────────────────

class DeviceEntry(BaseModel):
    device_id: str
    name: str
    connected: bool
    completion: float


class SyncStatusResponse(BaseModel):
    enabled: bool
    running: bool
    folder_id: str
    folder_state: str
    completion: float
    devices: list[DeviceEntry]
    error: str | None = None


class RescanResponse(BaseModel):
    ok: bool
    error: str | None = None


class DeviceIdResponse(BaseModel):
    device_id: str | None
    error: str | None = None


class AddDeviceRequest(BaseModel):
    device_id: str
    name: str = ""
    auto_accept: bool = True


class AddDeviceResponse(BaseModel):
    ok: bool
    error: str | None = None


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.get("/status", response_model=SyncStatusResponse)
def get_sync_status():
    """
    Return current Syncthing sync state for the Layla data folder.

    - `enabled` is False if syncthing_api_key is not set in config.json.
    - `running` is False if the Syncthing daemon is not reachable.
    - `folder_state` is one of: idle, syncing, error, unknown.
    - `completion` is 0.0–100.0 (this device's upload/download progress).
    - `devices` lists all configured peer devices and their sync completion.
    """
    status = syncthing_sync.get_status()
    return SyncStatusResponse(
        enabled=status["enabled"],
        running=status["running"],
        folder_id=status["folder_id"],
        folder_state=status["folder_state"],
        completion=status["completion"],
        devices=[DeviceEntry(**d) for d in status.get("devices", [])],
        error=status.get("error"),
    )


@router.post("/rescan", response_model=RescanResponse)
def trigger_rescan():
    """
    Ask Syncthing to immediately rescan the Layla data folder.
    Useful after bulk imports, knowledge additions, or manual file changes.
    Returns immediately; actual sync happens in the background.
    """
    result = syncthing_sync.trigger_rescan()
    return RescanResponse(ok=result["ok"], error=result.get("error"))


@router.get("/device-id", response_model=DeviceIdResponse)
def get_device_id():
    """
    Return this device's Syncthing device ID.
    Share this ID with peers so they can add this device in their Syncthing GUI.
    """
    dev_id = syncthing_sync.get_device_id()
    if dev_id is None:
        return DeviceIdResponse(
            device_id=None,
            error="Syncthing not running or not configured",
        )
    return DeviceIdResponse(device_id=dev_id)


@router.post("/add-device", response_model=AddDeviceResponse)
def add_device(req: AddDeviceRequest):
    """
    Add a peer device to Syncthing and share the Layla folder with it.

    Body:
      device_id   string  required  — The peer's Syncthing device ID
      name        string  optional  — Human-readable name for the device
      auto_accept bool    optional  — Auto-accept folders from this peer (default true)

    The peer must also add this device on their end (use /sync/device-id to
    get this device's ID).
    """
    if not req.device_id:
        raise HTTPException(status_code=400, detail="device_id is required")
    result = syncthing_sync.add_device(
        device_id=req.device_id,
        name=req.name,
        auto_accept=req.auto_accept,
    )
    return AddDeviceResponse(ok=result["ok"], error=result.get("error"))


@router.get("/setup-guide")
def setup_guide():
    """
    Return step-by-step instructions for setting up multi-device sync with Syncthing.
    """
    return {
        "title": "Layla Multi-Device Sync — Syncthing Setup",
        "steps": [
            {
                "step": 1,
                "title": "Install Syncthing on all devices",
                "detail": "Download from https://syncthing.net/downloads/ — available for Windows, macOS, Linux, Android.",
            },
            {
                "step": 2,
                "title": "Start Syncthing",
                "detail": "Run 'syncthing' or use the system tray app. The GUI opens at http://127.0.0.1:8384.",
            },
            {
                "step": 3,
                "title": "Get your API key",
                "detail": "In the Syncthing GUI: Actions → Settings → GUI → API Key. Copy it.",
            },
            {
                "step": 4,
                "title": "Configure Layla",
                "detail": (
                    "Add to agent/config.json:\n"
                    '  "syncthing_api_key": "<your-api-key>",\n'
                    '  "syncthing_folder_id": "layla-data"'
                ),
            },
            {
                "step": 5,
                "title": "Add the Layla data folder in Syncthing",
                "detail": (
                    "In Syncthing GUI: Add Folder → set Folder ID to 'layla-data' → "
                    "set path to the directory containing layla.db, chroma/, etc."
                ),
            },
            {
                "step": 6,
                "title": "Get this device's ID",
                "detail": "Call GET /sync/device-id or find it in Syncthing GUI → Actions → Show ID.",
            },
            {
                "step": 7,
                "title": "Add peer devices",
                "detail": (
                    "On each other device: call POST /sync/add-device with the peer's device_id. "
                    "Then accept the share request in the Syncthing GUI on the peer."
                ),
            },
            {
                "step": 8,
                "title": "Verify",
                "detail": "Call GET /sync/status — folder_state should be 'idle' and completion 100.0% when synced.",
            },
        ],
        "notes": [
            "Syncthing syncs at the file level; Layla's SQLite DB is synced as a whole file.",
            "Avoid writing to Layla on two devices simultaneously — this can cause DB conflicts.",
            "For write conflicts, Syncthing keeps both versions; delete the older .sync-conflict file.",
            "All sync is local-network or direct P2P — no data passes through Syncthing's servers.",
        ],
    }
