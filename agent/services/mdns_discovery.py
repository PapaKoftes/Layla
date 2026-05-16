"""
mdns_discovery.py — Zero-configuration local network discovery for Layla instances.

Uses the `zeroconf` library (pure Python) to broadcast and discover Layla
instances on the local network.  Service type: ``_layla._tcp.local.``

Metadata advertised:
  - device_name:    human-readable machine name
  - hardware_tier:  cpu | gpu_low | gpu_mid | gpu_high (from config)
  - models:         comma-separated list of available model names
  - api_port:       the HTTP port this instance listens on
  - version:        Layla version string
  - instance_id:    stable UUID persisted across restarts

All operations are safe to call even when zeroconf is not installed;
they degrade to no-ops with logged warnings.

Config keys in config.json:
  mdns_enabled         bool    Enable/disable mDNS broadcast (default: true)
  mdns_device_name     string  Override device name (default: hostname)
  hardware_tier        string  cpu | gpu_low | gpu_mid | gpu_high
  port                 int     HTTP port (default: 8000)
"""
from __future__ import annotations

import hashlib
import json
import logging
import platform
import socket
import threading
import time
import uuid
from pathlib import Path
from typing import Any

logger = logging.getLogger("layla.mdns")

# ── Constants ────────────────────────────────────────────────────────────────
SERVICE_TYPE = "_layla._tcp.local."
SERVICE_NAME_PREFIX = "Layla-"
_AGENT_DIR = Path(__file__).resolve().parent.parent
_INSTANCE_ID_FILE = _AGENT_DIR / ".governance" / "instance_id"
_DISCOVERY_TTL_S = 30  # how long a discovered peer stays valid without re-announcement

# ── Module state ─────────────────────────────────────────────────────────────
_zeroconf_instance = None
_service_info = None
_browser = None
_lock = threading.Lock()

# Discovered peers: {instance_id: {name, ip, port, tier, models, version, last_seen, ...}}
_discovered_peers: dict[str, dict[str, Any]] = {}
_peers_lock = threading.Lock()


# ── Instance ID (stable across restarts) ─────────────────────────────────────

def _get_or_create_instance_id() -> str:
    """Return a stable UUID for this Layla instance, persisted to disk."""
    try:
        if _INSTANCE_ID_FILE.exists():
            stored = _INSTANCE_ID_FILE.read_text(encoding="utf-8").strip()
            if stored and len(stored) >= 8:
                return stored
    except Exception:
        pass
    new_id = str(uuid.uuid4())
    try:
        _INSTANCE_ID_FILE.parent.mkdir(parents=True, exist_ok=True)
        _INSTANCE_ID_FILE.write_text(new_id, encoding="utf-8")
    except Exception as e:
        logger.debug("Could not persist instance_id: %s", e)
    return new_id


def get_instance_id() -> str:
    """Public accessor for the stable instance ID."""
    return _get_or_create_instance_id()


# ── Hardware tier detection ──────────────────────────────────────────────────

def detect_hardware_tier() -> str:
    """Detect hardware tier from available GPUs. Returns cpu|gpu_low|gpu_mid|gpu_high."""
    try:
        import torch
        if torch.cuda.is_available():
            vram_gb = torch.cuda.get_device_properties(0).total_mem / (1024 ** 3)
            if vram_gb >= 16:
                return "gpu_high"
            elif vram_gb >= 8:
                return "gpu_mid"
            else:
                return "gpu_low"
    except Exception:
        pass
    return "cpu"


def _get_available_models(cfg: dict) -> list[str]:
    """Return list of model names available on this instance."""
    models: list[str] = []
    # Check local GGUF
    model_path = (cfg.get("model_path") or "").strip()
    if model_path:
        p = Path(model_path)
        if p.exists():
            models.append(p.stem)
    # Check Ollama models
    ollama_url = (cfg.get("ollama_base_url") or cfg.get("llama_server_url") or "").strip()
    if ollama_url:
        try:
            import urllib.request
            req = urllib.request.Request(ollama_url.rstrip("/") + "/api/tags")
            with urllib.request.urlopen(req, timeout=3) as resp:
                data = json.loads(resp.read())
                for m in (data.get("models") or []):
                    name = m.get("name", "")
                    if name:
                        models.append(name)
        except Exception:
            remote_name = cfg.get("remote_model_name", "")
            if remote_name:
                models.append(remote_name)
    # Check remote model name
    if not models:
        remote = cfg.get("remote_model_name", "")
        if remote:
            models.append(remote)
    return models


def _get_version() -> str:
    """Return Layla version string."""
    try:
        ver_file = _AGENT_DIR / "VERSION"
        if ver_file.exists():
            return ver_file.read_text(encoding="utf-8").strip()
    except Exception:
        pass
    return "0.0.0"


def _get_lan_ip() -> str:
    """Get the LAN IP address of this machine."""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.settimeout(0)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        try:
            return socket.gethostbyname(socket.gethostname())
        except Exception:
            return "127.0.0.1"


# ── Service listener (receives peer announcements) ──────────────────────────

class _LaylaServiceListener:
    """Zeroconf listener that tracks discovered Layla peers on the LAN."""

    def __init__(self, zc):
        self._zc = zc

    def add_service(self, zc, type_, name):
        self._update_peer(zc, type_, name)

    def update_service(self, zc, type_, name):
        self._update_peer(zc, type_, name)

    def remove_service(self, zc, type_, name):
        # Try to find and remove the peer
        try:
            info = zc.get_service_info(type_, name)
            if info and info.properties:
                iid = info.properties.get(b"instance_id", b"").decode("utf-8", errors="replace")
                if iid:
                    with _peers_lock:
                        _discovered_peers.pop(iid, None)
                    logger.info("mDNS: peer removed: %s (%s)", name, iid[:8])
        except Exception:
            pass

    def _update_peer(self, zc, type_, name):
        try:
            info = zc.get_service_info(type_, name)
            if not info or not info.properties:
                return
            props = {k.decode("utf-8", errors="replace"): v.decode("utf-8", errors="replace")
                     for k, v in info.properties.items()}
            iid = props.get("instance_id", "")
            if not iid:
                return
            # Skip self
            my_id = _get_or_create_instance_id()
            if iid == my_id:
                return

            # Parse IP addresses
            addresses = []
            try:
                for addr in info.addresses:
                    addresses.append(socket.inet_ntoa(addr))
            except Exception:
                pass
            if not addresses:
                try:
                    addresses = [info.parsed_addresses()[0]]
                except Exception:
                    return

            peer = {
                "instance_id": iid,
                "name": props.get("device_name", name),
                "ip": addresses[0],
                "port": int(props.get("api_port", info.port or 8000)),
                "hardware_tier": props.get("hardware_tier", "cpu"),
                "models": [m.strip() for m in props.get("models", "").split(",") if m.strip()],
                "version": props.get("version", "?"),
                "last_seen": time.time(),
                "service_name": name,
                "all_addresses": addresses,
            }
            with _peers_lock:
                _discovered_peers[iid] = peer
            logger.info("mDNS: discovered peer %s @ %s:%s (tier=%s, models=%s)",
                        peer["name"], peer["ip"], peer["port"],
                        peer["hardware_tier"], peer["models"])
        except Exception as e:
            logger.debug("mDNS: listener error for %s: %s", name, e)


# ── Start / stop service ────────────────────────────────────────────────────

def start_service(cfg: dict | None = None) -> bool:
    """
    Start mDNS broadcast + discovery.  Safe to call multiple times.
    Returns True if service started, False on error or if disabled.
    """
    global _zeroconf_instance, _service_info, _browser

    if cfg is None:
        try:
            import runtime_safety
            cfg = runtime_safety.load_config()
        except Exception:
            cfg = {}

    if not cfg.get("mdns_enabled", True):
        logger.info("mDNS: disabled by config (mdns_enabled=false)")
        return False

    try:
        from zeroconf import ServiceBrowser, ServiceInfo, Zeroconf
    except ImportError:
        logger.warning("mDNS: zeroconf not installed. Run: pip install zeroconf")
        return False

    with _lock:
        if _zeroconf_instance is not None:
            return True  # already running

        try:
            instance_id = _get_or_create_instance_id()
            device_name = (cfg.get("mdns_device_name") or "").strip() or platform.node() or "layla-device"
            tier = (cfg.get("hardware_tier") or "").strip() or detect_hardware_tier()
            models = _get_available_models(cfg)
            port = int(cfg.get("port", 8000))
            version = _get_version()
            lan_ip = _get_lan_ip()

            # Service name must be unique on the network
            short_id = hashlib.md5(instance_id.encode()).hexdigest()[:6]
            service_name = f"{SERVICE_NAME_PREFIX}{device_name}-{short_id}.{SERVICE_TYPE}"

            properties = {
                "instance_id": instance_id,
                "device_name": device_name,
                "hardware_tier": tier,
                "models": ",".join(models[:10]),  # cap at 10 model names
                "api_port": str(port),
                "version": version,
                "platform": platform.system(),
            }

            _service_info = ServiceInfo(
                SERVICE_TYPE,
                service_name,
                addresses=[socket.inet_aton(lan_ip)],
                port=port,
                properties=properties,
                server=f"{device_name}.local.",
            )

            _zeroconf_instance = Zeroconf()
            _zeroconf_instance.register_service(_service_info)
            logger.info("mDNS: broadcasting as '%s' @ %s:%s (tier=%s, id=%s...)",
                        device_name, lan_ip, port, tier, instance_id[:8])

            # Start browsing for other Layla instances
            listener = _LaylaServiceListener(_zeroconf_instance)
            _browser = ServiceBrowser(_zeroconf_instance, SERVICE_TYPE, listener)
            logger.info("mDNS: listening for other Layla instances on %s", SERVICE_TYPE)

            return True
        except Exception as e:
            logger.exception("mDNS: failed to start service: %s", e)
            _zeroconf_instance = None
            _service_info = None
            _browser = None
            return False


def stop_service() -> None:
    """Stop mDNS broadcast + discovery.  Safe to call even if not started."""
    global _zeroconf_instance, _service_info, _browser

    with _lock:
        if _zeroconf_instance is None:
            return
        try:
            if _service_info:
                _zeroconf_instance.unregister_service(_service_info)
            _zeroconf_instance.close()
            logger.info("mDNS: service stopped")
        except Exception as e:
            logger.debug("mDNS: error during shutdown: %s", e)
        finally:
            _zeroconf_instance = None
            _service_info = None
            _browser = None


def is_running() -> bool:
    """True if mDNS service is currently broadcasting."""
    return _zeroconf_instance is not None


# ── Peer discovery API ──────────────────────────────────────────────────────

def get_discovered_peers(max_age_s: float = 120.0) -> list[dict[str, Any]]:
    """
    Return list of recently-seen Layla peers on the network.
    Filters out peers not seen within max_age_s seconds.
    """
    now = time.time()
    with _peers_lock:
        peers = []
        stale_ids = []
        for iid, p in _discovered_peers.items():
            age = now - p.get("last_seen", 0)
            if age <= max_age_s:
                peers.append({**p, "age_seconds": round(age, 1)})
            else:
                stale_ids.append(iid)
        for iid in stale_ids:
            _discovered_peers.pop(iid, None)
    return sorted(peers, key=lambda x: x.get("last_seen", 0), reverse=True)


def get_peer_by_id(instance_id: str) -> dict[str, Any] | None:
    """Look up a specific peer by instance_id."""
    with _peers_lock:
        return _discovered_peers.get(instance_id)


def get_best_peer_for_inference(min_tier: str = "cpu") -> dict[str, Any] | None:
    """
    Return the best available peer for inference offloading.
    Ranks by hardware tier, preferring gpu_high > gpu_mid > gpu_low > cpu.
    Only returns peers with tier >= min_tier.
    """
    tier_rank = {"cpu": 0, "gpu_low": 1, "gpu_mid": 2, "gpu_high": 3}
    min_rank = tier_rank.get(min_tier, 0)
    peers = get_discovered_peers(max_age_s=60.0)
    candidates = [p for p in peers if tier_rank.get(p.get("hardware_tier", "cpu"), 0) >= min_rank]
    if not candidates:
        return None
    candidates.sort(key=lambda p: tier_rank.get(p.get("hardware_tier", "cpu"), 0), reverse=True)
    return candidates[0]


def peer_count() -> int:
    """Return number of currently-known peers (including stale)."""
    with _peers_lock:
        return len(_discovered_peers)


# ── Health check ─────────────────────────────────────────────────────────────

def check_peer_health(peer: dict[str, Any], timeout: float = 3.0) -> dict[str, Any]:
    """
    Ping a discovered peer's /health endpoint to verify it's reachable.
    Returns: {"reachable": bool, "latency_ms": float, "status": str, "error": str|None}
    """
    import urllib.error
    import urllib.request

    ip = peer.get("ip", "")
    port = peer.get("port", 8000)
    url = f"http://{ip}:{port}/health"
    t0 = time.perf_counter()
    try:
        req = urllib.request.Request(url, method="GET")
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            latency = (time.perf_counter() - t0) * 1000
            data = json.loads(resp.read())
            return {
                "reachable": True,
                "latency_ms": round(latency, 1),
                "status": data.get("status", "ok"),
                "error": None,
            }
    except Exception as e:
        latency = (time.perf_counter() - t0) * 1000
        return {
            "reachable": False,
            "latency_ms": round(latency, 1),
            "status": "unreachable",
            "error": str(e),
        }


# ── Summary for diagnostics ─────────────────────────────────────────────────

def get_status() -> dict[str, Any]:
    """Return full mDNS status for diagnostics / UI display."""
    peers = get_discovered_peers()
    return {
        "enabled": is_running(),
        "instance_id": _get_or_create_instance_id(),
        "service_type": SERVICE_TYPE,
        "peer_count": len(peers),
        "peers": peers,
        "zeroconf_installed": _is_zeroconf_available(),
    }


def _is_zeroconf_available() -> bool:
    """Check if zeroconf library is importable."""
    try:
        import zeroconf  # noqa: F401
        return True
    except ImportError:
        return False
