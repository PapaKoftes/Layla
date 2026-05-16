"""
pairing.py — Device pairing, mDNS discovery, and cluster management endpoints.

Endpoints:
  GET  /pairing/peers             — List discovered Layla instances on the LAN
  GET  /pairing/status            — mDNS service status + instance identity
  POST /pairing/start             — Start mDNS broadcasting + discovery
  POST /pairing/stop              — Stop mDNS service
  POST /pairing/pair              — Initiate pairing with a peer via 6-digit PIN
  POST /pairing/confirm           — Confirm pairing (verify PIN)
  GET  /pairing/paired-devices    — List all paired devices
  DELETE /pairing/{instance_id}   — Unpair a device
  GET  /pairing/peer/{id}/health  — Health-check a specific peer
  POST /pairing/refresh           — Force re-scan for peers

All endpoints degrade gracefully when zeroconf is not installed.

Configuration keys:
  mdns_enabled       bool    Enable mDNS broadcast (default: true)
  mdns_device_name   string  Override device name (default: hostname)
  pairing_pin_ttl    int     PIN validity in seconds (default: 300)
"""
from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
import secrets
import time
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

logger = logging.getLogger("layla.pairing")

router = APIRouter(prefix="/pairing", tags=["pairing"])

_AGENT_DIR = Path(__file__).resolve().parent.parent
_PAIRED_DEVICES_FILE = _AGENT_DIR / ".governance" / "paired_devices.json"

# In-memory pending pairing sessions: {pin: {instance_id, created_at, shared_secret, peer_name}}
_pending_pairings: dict[str, dict[str, Any]] = {}
_PAIRING_LOCK = __import__("threading").Lock()


# ── Request / response models ────────────────────────────────────────────────

class PeerInfo(BaseModel):
    instance_id: str
    name: str
    ip: str
    port: int
    hardware_tier: str
    models: list[str]
    version: str
    age_seconds: float


class DiscoveryStatusResponse(BaseModel):
    enabled: bool
    instance_id: str
    service_type: str
    peer_count: int
    peers: list[dict[str, Any]]
    zeroconf_installed: bool


class PairRequest(BaseModel):
    instance_id: str
    device_name: str = ""


class PairResponse(BaseModel):
    ok: bool
    pin: str | None = None
    ttl_seconds: int = 300
    error: str | None = None


class ConfirmPairRequest(BaseModel):
    pin: str
    instance_id: str
    shared_secret: str = ""


class ConfirmPairResponse(BaseModel):
    ok: bool
    device_name: str = ""
    error: str | None = None


class PairedDevice(BaseModel):
    instance_id: str
    name: str
    hardware_tier: str
    paired_at: float
    last_seen: float | None = None
    permissions: dict[str, bool]


class UnpairResponse(BaseModel):
    ok: bool
    error: str | None = None


class PeerHealthResponse(BaseModel):
    reachable: bool
    latency_ms: float
    status: str
    error: str | None = None


# ── Paired device persistence ────────────────────────────────────────────────

def _load_paired_devices() -> dict[str, dict[str, Any]]:
    """Load paired devices from disk."""
    try:
        if _PAIRED_DEVICES_FILE.exists():
            data = json.loads(_PAIRED_DEVICES_FILE.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                return data
    except Exception as e:
        logger.debug("Failed to load paired devices: %s", e)
    return {}


def _save_paired_devices(devices: dict[str, dict[str, Any]]) -> None:
    """Save paired devices to disk."""
    try:
        _PAIRED_DEVICES_FILE.parent.mkdir(parents=True, exist_ok=True)
        _PAIRED_DEVICES_FILE.write_text(
            json.dumps(devices, indent=2, default=str),
            encoding="utf-8",
        )
    except Exception as e:
        logger.warning("Failed to save paired devices: %s", e)


def _generate_pin() -> str:
    """Generate a cryptographically random 6-digit PIN."""
    return f"{secrets.randbelow(1000000):06d}"


def _generate_shared_secret() -> str:
    """Generate a shared secret for peer-to-peer auth."""
    return secrets.token_hex(32)


def _cleanup_expired_pins(ttl: int = 300) -> None:
    """Remove expired pending pairings."""
    now = time.time()
    with _PAIRING_LOCK:
        expired = [pin for pin, data in _pending_pairings.items()
                    if now - data.get("created_at", 0) > ttl]
        for pin in expired:
            _pending_pairings.pop(pin, None)


# ── Endpoints ────────────────────────────────────────────────────────────────

@router.get("/peers", response_model=list[PeerInfo])
def list_peers():
    """
    List all Layla instances discovered on the local network via mDNS.
    Returns empty list if mDNS is not running or no peers found.
    """
    try:
        from services.mdns_discovery import get_discovered_peers
        peers = get_discovered_peers(max_age_s=120.0)
        return [PeerInfo(**{k: v for k, v in p.items()
                           if k in PeerInfo.model_fields}) for p in peers]
    except ImportError:
        return []
    except Exception as e:
        logger.debug("list_peers error: %s", e)
        return []


@router.get("/status", response_model=DiscoveryStatusResponse)
def discovery_status():
    """Return mDNS service status: whether broadcasting, instance ID, and peer count."""
    try:
        from services.mdns_discovery import get_status
        status = get_status()
        return DiscoveryStatusResponse(**status)
    except ImportError:
        from services.mdns_discovery import get_instance_id
        return DiscoveryStatusResponse(
            enabled=False,
            instance_id=get_instance_id(),
            service_type="_layla._tcp.local.",
            peer_count=0,
            peers=[],
            zeroconf_installed=False,
        )
    except Exception:
        return DiscoveryStatusResponse(
            enabled=False,
            instance_id="unknown",
            service_type="_layla._tcp.local.",
            peer_count=0,
            peers=[],
            zeroconf_installed=False,
        )


@router.post("/start")
def start_discovery():
    """Start mDNS broadcasting and peer discovery."""
    try:
        from services.mdns_discovery import start_service
        ok = start_service()
        return {"ok": ok, "error": None if ok else "Failed to start mDNS. Is zeroconf installed?"}
    except ImportError:
        return {"ok": False, "error": "zeroconf not installed. Run: pip install zeroconf"}
    except Exception as e:
        return {"ok": False, "error": str(e)}


@router.post("/stop")
def stop_discovery():
    """Stop mDNS broadcasting and peer discovery."""
    try:
        from services.mdns_discovery import stop_service
        stop_service()
        return {"ok": True}
    except Exception as e:
        return {"ok": False, "error": str(e)}


@router.post("/pair", response_model=PairResponse)
def initiate_pairing(req: PairRequest):
    """
    Initiate pairing with a discovered peer.

    Generates a 6-digit PIN that must be entered on the peer device to confirm.
    The PIN is valid for `pairing_pin_ttl` seconds (default 300 = 5 minutes).

    Body:
      instance_id   string  required  — The peer's instance ID (from /pairing/peers)
      device_name   string  optional  — Human-readable name for this pairing
    """
    if not req.instance_id:
        raise HTTPException(status_code=400, detail="instance_id is required")

    # Check if already paired
    devices = _load_paired_devices()
    if req.instance_id in devices:
        return PairResponse(ok=False, error="Device already paired")

    _cleanup_expired_pins()

    pin = _generate_pin()
    shared_secret = _generate_shared_secret()

    try:
        import runtime_safety
        cfg = runtime_safety.load_config()
        ttl = int(cfg.get("pairing_pin_ttl", 300) or 300)
    except Exception:
        ttl = 300

    with _PAIRING_LOCK:
        _pending_pairings[pin] = {
            "instance_id": req.instance_id,
            "peer_name": req.device_name or req.instance_id[:8],
            "shared_secret": shared_secret,
            "created_at": time.time(),
        }

    logger.info("Pairing initiated with %s (PIN generated, TTL=%ds)", req.instance_id[:8], ttl)
    return PairResponse(ok=True, pin=pin, ttl_seconds=ttl)


@router.post("/confirm", response_model=ConfirmPairResponse)
def confirm_pairing(req: ConfirmPairRequest):
    """
    Confirm pairing by entering the 6-digit PIN shown on the initiating device.

    Body:
      pin           string  required  — The 6-digit PIN from the initiator
      instance_id   string  required  — The initiating peer's instance ID
      shared_secret string  optional  — For mutual authentication (advanced)
    """
    if not req.pin or not req.instance_id:
        raise HTTPException(status_code=400, detail="pin and instance_id are required")

    _cleanup_expired_pins()

    with _PAIRING_LOCK:
        pairing = _pending_pairings.get(req.pin)
        if not pairing:
            return ConfirmPairResponse(ok=False, error="Invalid or expired PIN")
        if pairing["instance_id"] != req.instance_id:
            return ConfirmPairResponse(ok=False, error="PIN does not match this device")
        # PIN is valid — consume it
        _pending_pairings.pop(req.pin, None)

    # Get peer info for metadata
    peer_name = pairing.get("peer_name", req.instance_id[:8])
    peer_tier = "cpu"
    try:
        from services.mdns_discovery import get_peer_by_id
        peer = get_peer_by_id(req.instance_id)
        if peer:
            peer_name = peer.get("name", peer_name)
            peer_tier = peer.get("hardware_tier", "cpu")
    except Exception:
        pass

    # Store paired device
    devices = _load_paired_devices()
    devices[req.instance_id] = {
        "name": peer_name,
        "hardware_tier": peer_tier,
        "paired_at": time.time(),
        "last_seen": time.time(),
        "shared_secret_hash": hashlib.sha256(pairing["shared_secret"].encode()).hexdigest(),
        "permissions": {
            "read_learnings": True,
            "write_learnings": False,
            "inference_offload": True,
            "sync_knowledge": True,
            "remote_tools": False,
        },
    }
    _save_paired_devices(devices)

    logger.info("Pairing confirmed with %s (%s)", peer_name, req.instance_id[:8])
    return ConfirmPairResponse(ok=True, device_name=peer_name)


@router.get("/paired-devices", response_model=list[PairedDevice])
def list_paired_devices():
    """Return all paired devices with their permissions and last-seen timestamps."""
    devices = _load_paired_devices()

    # Enrich with live discovery data
    try:
        from services.mdns_discovery import get_discovered_peers
        peers = {p["instance_id"]: p for p in get_discovered_peers()}
    except Exception:
        peers = {}

    result = []
    for iid, dev in devices.items():
        live = peers.get(iid, {})
        result.append(PairedDevice(
            instance_id=iid,
            name=dev.get("name", iid[:8]),
            hardware_tier=live.get("hardware_tier", dev.get("hardware_tier", "cpu")),
            paired_at=dev.get("paired_at", 0),
            last_seen=live.get("last_seen", dev.get("last_seen")),
            permissions=dev.get("permissions", {}),
        ))
    return result


@router.delete("/{instance_id}", response_model=UnpairResponse)
def unpair_device(instance_id: str):
    """Remove a paired device. This does NOT affect the peer — they must also unpair."""
    devices = _load_paired_devices()
    if instance_id not in devices:
        return UnpairResponse(ok=False, error="Device not found")
    name = devices[instance_id].get("name", instance_id[:8])
    devices.pop(instance_id)
    _save_paired_devices(devices)
    logger.info("Unpaired device %s (%s)", name, instance_id[:8])
    return UnpairResponse(ok=True)


@router.get("/peer/{instance_id}/health", response_model=PeerHealthResponse)
def peer_health(instance_id: str):
    """Health-check a specific discovered peer by hitting its /health endpoint."""
    try:
        from services.mdns_discovery import check_peer_health, get_peer_by_id
        peer = get_peer_by_id(instance_id)
        if not peer:
            return PeerHealthResponse(
                reachable=False, latency_ms=0, status="not_found",
                error="Peer not found in discovery cache",
            )
        result = check_peer_health(peer)
        return PeerHealthResponse(**result)
    except Exception as e:
        return PeerHealthResponse(
            reachable=False, latency_ms=0, status="error", error=str(e),
        )


@router.post("/refresh")
def refresh_peers():
    """
    Force refresh peer discovery.
    If mDNS is not running, starts it first.
    """
    try:
        from services.mdns_discovery import get_discovered_peers, is_running, start_service
        if not is_running():
            start_service()
        # Return current peers after a brief wait
        import time
        time.sleep(0.5)
        peers = get_discovered_peers()
        return {"ok": True, "peer_count": len(peers), "peers": peers}
    except Exception as e:
        return {"ok": False, "peer_count": 0, "peers": [], "error": str(e)}


@router.patch("/{instance_id}/permissions")
def update_permissions(instance_id: str, permissions: dict[str, bool]):
    """
    Update permissions for a paired device.

    Available permission keys:
      read_learnings    — Can read this device's learnings
      write_learnings   — Can write learnings to this device
      inference_offload — Can send inference requests to this device
      sync_knowledge    — Can sync knowledge base entries
      remote_tools      — Can execute tools remotely on this device
    """
    devices = _load_paired_devices()
    if instance_id not in devices:
        raise HTTPException(status_code=404, detail="Device not paired")

    valid_keys = {"read_learnings", "write_learnings", "inference_offload",
                  "sync_knowledge", "remote_tools"}
    for k, v in permissions.items():
        if k in valid_keys:
            devices[instance_id].setdefault("permissions", {})[k] = bool(v)

    _save_paired_devices(devices)
    return {"ok": True, "permissions": devices[instance_id].get("permissions", {})}
