"""Cluster Network Manager — mesh networking for QUEEN + DRONE topology.

Manages peer discovery, heartbeats, task submission to remote nodes,
and knowledge sync across the Layla cluster.

Phase 2B of the distributed infrastructure plan.
"""
from __future__ import annotations

import enum
import json
import logging
import threading
import time
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger("layla")

# ── Constants ────────────────────────────────────────────────────────────

CLUSTER_CONFIG_FILE = Path(__file__).resolve().parent.parent.parent / "cluster_config.json"
HEARTBEAT_TIMEOUT_FACTOR = 3  # Mark peer offline after 3x heartbeat interval


# ── Enums ────────────────────────────────────────────────────────────────

class NodeRole(enum.Enum):
    QUEEN = "queen"
    DRONE = "drone"


class PeerStatus(enum.Enum):
    ONLINE = "online"
    DEGRADED = "degraded"   # Missed 1 heartbeat
    OFFLINE = "offline"     # Missed 3+ heartbeats
    PAIRING = "pairing"     # In pairing flow


# ── Peer dataclass ───────────────────────────────────────────────────────

@dataclass
class Peer:
    """Represents a known node in the cluster."""
    instance_id: str
    name: str = ""
    role: NodeRole = NodeRole.DRONE
    address: str = ""           # e.g. "http://100.x.x.x:8000" (Tailscale IP)
    hardware_tier: str = "cpu"  # cpu | gpu_low | gpu_mid | gpu_high
    status: PeerStatus = PeerStatus.OFFLINE
    last_heartbeat: float = 0.0  # time.time()
    current_load: float = 0.0    # 0-1 CPU usage
    current_tasks: int = 0
    max_concurrent_tasks: int = 2
    governor_mode: str = "whisper"
    capabilities: list[str] = field(default_factory=list)
    version: str = ""
    latency_ms: float = 0.0

    def is_online(self) -> bool:
        return self.status in (PeerStatus.ONLINE, PeerStatus.DEGRADED)

    def has_capability(self, task_type: str) -> bool:
        """Check if peer can handle this task type."""
        if not self.capabilities:
            return True  # No declared caps = can do anything
        return task_type in self.capabilities

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["role"] = self.role.value
        d["status"] = self.status.value
        return d

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> Peer:
        d = dict(d)
        if "role" in d and isinstance(d["role"], str):
            d["role"] = NodeRole(d["role"])
        if "status" in d and isinstance(d["status"], str):
            d["status"] = PeerStatus(d["status"])
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})


# ── Cluster Config I/O ───────────────────────────────────────────────────

def load_cluster_config() -> dict[str, Any]:
    """Load cluster_config.json (or return defaults)."""
    if CLUSTER_CONFIG_FILE.exists():
        try:
            return json.loads(CLUSTER_CONFIG_FILE.read_text(encoding="utf-8"))
        except Exception as e:
            logger.warning("Failed to read cluster config: %s", e)
    return {
        "cluster_enabled": False,
        "node_role": "queen",
        "node_name": "",
        "cluster_id": "",
        "cluster_secret_hash": "",
        "peers": {},
    }


def save_cluster_config(config: dict[str, Any]) -> None:
    """Persist cluster_config.json."""
    try:
        CLUSTER_CONFIG_FILE.write_text(
            json.dumps(config, indent=4, ensure_ascii=False),
            encoding="utf-8",
        )
    except Exception as e:
        logger.error("Failed to save cluster config: %s", e)


# ── ClusterNetwork ───────────────────────────────────────────────────────

class ClusterNetwork:
    """Manages the cluster mesh: peers, heartbeats, task dispatch, sync.

    Integrates with:
    - ``services.mdns_discovery`` for LAN peer discovery
    - ``services.tailscale_manager`` for WAN connectivity
    - ``services.tunnel_auth`` for request authentication
    - ``services.resource_governor`` for resource-aware decisions
    """

    def __init__(self, cfg: dict[str, Any]):
        self._cfg = cfg
        self._cluster_config = load_cluster_config()

        # Role & identity
        self.role = NodeRole(cfg.get("node_role", self._cluster_config.get("node_role", "queen")))
        self._node_name = self._cluster_config.get("node_name", "")
        self._cluster_id = self._cluster_config.get("cluster_id", "")

        # Instance ID (reuse mDNS stable ID)
        try:
            from services.mdns_discovery import get_instance_id
            self._instance_id = get_instance_id()
        except Exception:
            import uuid
            self._instance_id = uuid.uuid4().hex[:12]

        # Peers
        self.peers: dict[str, Peer] = {}
        self._peers_lock = threading.RLock()
        self._load_known_peers()

        # Heartbeat
        self._heartbeat_interval = max(10, cfg.get("cluster_heartbeat_interval", 30))
        self._heartbeat_thread: threading.Thread | None = None
        self._stop_event = threading.Event()

        # HTTP client (lazy)
        self._http_client = None

        self._enabled = cfg.get("cluster_enabled", False) and bool(self._cluster_id)

        # Phase 5D: Tailscale auto-connect — use Tailscale IP as advertised URL
        self._tailscale_ip: str = ""
        self._advertised_url: str = ""
        if self._enabled:
            try:
                from services.tailscale_manager import get_tailscale_ip, is_available
                if is_available():
                    self._tailscale_ip = get_tailscale_ip() or ""
                    if self._tailscale_ip:
                        self._advertised_url = f"http://{self._tailscale_ip}:8000"
                        logger.info("ClusterNetwork: Tailscale IP detected: %s", self._tailscale_ip)
            except Exception as _ts_err:
                logger.debug("Tailscale auto-connect skipped: %s", _ts_err)

        logger.info(
            "ClusterNetwork init: role=%s, id=%s, enabled=%s, peers=%d%s",
            self.role.value,
            self._instance_id[:8],
            self._enabled,
            len(self.peers),
            f", tailscale={self._tailscale_ip}" if self._tailscale_ip else "",
        )

    # ── Properties ────────────────────────────────────────────────────

    @property
    def instance_id(self) -> str:
        return self._instance_id

    @property
    def enabled(self) -> bool:
        return self._enabled

    @property
    def node_name(self) -> str:
        return self._node_name or self._instance_id[:8]

    @property
    def cluster_id(self) -> str:
        return self._cluster_id

    # ── Peer management ──────────────────────────────────────────────

    def _load_known_peers(self) -> None:
        """Load peers from cluster_config.json."""
        peers_data = self._cluster_config.get("peers", {})
        with self._peers_lock:
            for pid, pdata in peers_data.items():
                if isinstance(pdata, dict):
                    try:
                        self.peers[pid] = Peer.from_dict({"instance_id": pid, **pdata})
                    except Exception as e:
                        logger.debug("Skip invalid peer %s: %s", pid, e)

    def add_peer(self, peer: Peer) -> None:
        """Register or update a peer."""
        with self._peers_lock:
            self.peers[peer.instance_id] = peer
        self._persist_peers()

    def remove_peer(self, instance_id: str) -> bool:
        """Remove a peer from the cluster."""
        with self._peers_lock:
            removed = self.peers.pop(instance_id, None)
        if removed:
            self._persist_peers()
            logger.info("Removed peer %s (%s)", instance_id[:8], removed.name)
        return removed is not None

    def get_peer(self, instance_id: str) -> Peer | None:
        with self._peers_lock:
            return self.peers.get(instance_id)

    def get_online_peers(self) -> list[Peer]:
        """Get all peers that are currently reachable."""
        with self._peers_lock:
            return [p for p in self.peers.values() if p.is_online()]

    def get_online_drones(self) -> list[Peer]:
        """Get all online DRONE nodes."""
        return [p for p in self.get_online_peers() if p.role == NodeRole.DRONE]

    def _persist_peers(self) -> None:
        """Save current peers to cluster_config.json."""
        with self._peers_lock:
            peers_dict = {}
            for pid, peer in self.peers.items():
                d = peer.to_dict()
                d.pop("instance_id", None)
                peers_dict[pid] = d
        config = load_cluster_config()
        config["peers"] = peers_dict
        save_cluster_config(config)

    # ── Discovery integration ────────────────────────────────────────

    def discover_peers(self) -> list[Peer]:
        """Discover peers via mDNS and update internal state."""
        discovered = []
        try:
            from services.mdns_discovery import get_discovered_peers
            mdns_peers = get_discovered_peers(max_age_s=120.0)
            for mp in mdns_peers:
                pid = mp.get("instance_id", "")
                if not pid or pid == self._instance_id:
                    continue  # Skip self
                peer = Peer(
                    instance_id=pid,
                    name=mp.get("name", mp.get("service_name", "")),
                    address=f"http://{mp.get('ip', '')}:{mp.get('port', 8000)}",
                    hardware_tier=mp.get("hardware_tier", "cpu"),
                    status=PeerStatus.ONLINE,
                    last_heartbeat=time.time(),
                    version=mp.get("version", ""),
                )
                with self._peers_lock:
                    existing = self.peers.get(pid)
                    if existing:
                        # Update address/tier but preserve role and config
                        existing.address = peer.address
                        existing.hardware_tier = peer.hardware_tier
                        existing.version = peer.version
                        if existing.status == PeerStatus.OFFLINE:
                            existing.status = PeerStatus.ONLINE
                            existing.last_heartbeat = time.time()
                    else:
                        self.peers[pid] = peer
                discovered.append(pid)
        except Exception as e:
            logger.debug("mDNS peer discovery: %s", e)

        # Also try Tailscale for WAN peers
        try:
            from services.tailscale_manager import get_status
            ts = get_status()
            if ts.get("running"):
                # Tailscale peers are configured in cluster_config, not auto-discovered
                pass
        except Exception:
            pass

        return [self.peers[pid] for pid in discovered if pid in self.peers]

    # ── Heartbeat ────────────────────────────────────────────────────

    def start_heartbeat(self) -> None:
        """Start the background heartbeat loop."""
        if not self._enabled:
            return
        if self._heartbeat_thread and self._heartbeat_thread.is_alive():
            return
        self._stop_event.clear()
        self._heartbeat_thread = threading.Thread(
            target=self._heartbeat_loop,
            name="cluster-heartbeat",
            daemon=True,
        )
        self._heartbeat_thread.start()
        logger.info("Cluster heartbeat started (every %ds)", self._heartbeat_interval)

    def stop_heartbeat(self) -> None:
        """Stop the heartbeat loop."""
        self._stop_event.set()
        if self._heartbeat_thread:
            self._heartbeat_thread.join(timeout=5)
            self._heartbeat_thread = None

    def _heartbeat_loop(self) -> None:
        """Periodically send heartbeats and check peer health."""
        while not self._stop_event.is_set():
            try:
                self._check_peer_health()
                self._send_heartbeats()
            except Exception as e:
                logger.debug("Heartbeat loop error: %s", e)
            self._stop_event.wait(self._heartbeat_interval)

    def _send_heartbeats(self) -> None:
        """Send heartbeat to all known peers."""
        status_payload = self._build_status_payload()
        with self._peers_lock:
            targets = list(self.peers.values())
        for peer in targets:
            if not peer.address:
                continue
            try:
                resp = self._post(peer.address, "/cluster/heartbeat", status_payload)
                if resp and resp.get("ok"):
                    peer.last_heartbeat = time.time()
                    peer.status = PeerStatus.ONLINE
                    # Update peer info from response
                    if "governor_mode" in resp:
                        peer.governor_mode = resp["governor_mode"]
                    if "current_load" in resp:
                        peer.current_load = resp["current_load"]
                    if "current_tasks" in resp:
                        peer.current_tasks = resp["current_tasks"]
            except Exception:
                pass  # Health check handles status demotion

    def _check_peer_health(self) -> None:
        """Demote peers that have missed heartbeats."""
        now = time.time()
        timeout = self._heartbeat_interval * HEARTBEAT_TIMEOUT_FACTOR
        with self._peers_lock:
            for peer in self.peers.values():
                if peer.last_heartbeat == 0:
                    continue
                age = now - peer.last_heartbeat
                if age > timeout * 2:
                    if peer.status != PeerStatus.OFFLINE:
                        logger.info("Peer %s (%s) → OFFLINE", peer.instance_id[:8], peer.name)
                        peer.status = PeerStatus.OFFLINE
                elif age > timeout:
                    if peer.status == PeerStatus.ONLINE:
                        peer.status = PeerStatus.DEGRADED

    def _build_status_payload(self) -> dict[str, Any]:
        """Build heartbeat payload with this node's status."""
        status: dict[str, Any] = {
            "instance_id": self._instance_id,
            "name": self.node_name,
            "role": self.role.value,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        try:
            from services.resource_governor import get_mode
            status["governor_mode"] = get_mode().value
        except Exception:
            status["governor_mode"] = "whisper"
        try:
            import psutil
            status["current_load"] = psutil.cpu_percent(interval=0) / 100.0
        except Exception:
            status["current_load"] = 0.0
        try:
            from services.work_unit import get_task_queue
            running = get_task_queue().get_running(self._instance_id)
            status["current_tasks"] = len(running)
        except Exception:
            status["current_tasks"] = 0
        return status

    # ── Task submission (to remote nodes) ────────────────────────────

    def submit_task(self, peer: Peer, task_dict: dict[str, Any]) -> dict[str, Any] | None:
        """Submit a task to a remote peer node.

        Returns the response dict (with task ID) or None on failure.
        """
        if not peer.address:
            logger.warning("Cannot submit task to peer %s: no address", peer.instance_id[:8])
            return None
        try:
            resp = self._post(peer.address, "/cluster/task/submit", task_dict)
            return resp
        except Exception as e:
            logger.warning("Task submission to %s failed: %s", peer.instance_id[:8], e)
            return None

    def get_task_status(self, peer: Peer, task_id: str) -> dict[str, Any] | None:
        """Poll task status on a remote peer."""
        if not peer.address:
            return None
        try:
            return self._get(peer.address, f"/cluster/task/{task_id}/status")
        except Exception as e:
            logger.debug("Task status poll failed: %s", e)
            return None

    def cancel_remote_task(self, peer: Peer, task_id: str) -> bool:
        """Cancel a task on a remote peer."""
        if not peer.address:
            return False
        try:
            resp = self._post(peer.address, f"/cluster/task/{task_id}/cancel", {})
            return bool(resp and resp.get("ok"))
        except Exception:
            return False

    # ── Knowledge sync ───────────────────────────────────────────────

    def sync_push(self, peer: Peer, learnings: list[dict]) -> bool:
        """Push new learnings to a remote peer."""
        if not peer.address or not learnings:
            return False
        try:
            resp = self._post(peer.address, "/cluster/sync/push", {"learnings": learnings})
            return bool(resp and resp.get("ok"))
        except Exception as e:
            logger.debug("Sync push to %s failed: %s", peer.instance_id[:8], e)
            return False

    def sync_pull(self, peer: Peer, since: str) -> list[dict]:
        """Pull learnings from a remote peer since a timestamp."""
        if not peer.address:
            return []
        try:
            resp = self._post(peer.address, "/cluster/sync/pull", {"since": since})
            if resp and "learnings" in resp:
                return resp["learnings"]
        except Exception as e:
            logger.debug("Sync pull from %s failed: %s", peer.instance_id[:8], e)
        return []

    # ── HTTP helpers ─────────────────────────────────────────────────

    def _get_auth_headers(self) -> dict[str, str]:
        """Build Authorization header from cluster secret."""
        secret = self._cluster_config.get("cluster_secret_hash", "")
        if not secret:
            # Try runtime safety config
            from runtime_safety import load_config
            cfg = load_config()
            secret = cfg.get("tunnel_token_hash", "")
        if secret:
            return {"Authorization": f"Bearer {secret}"}
        return {}

    def _post(self, base_url: str, path: str, data: dict) -> dict[str, Any] | None:
        """POST JSON to a peer endpoint."""
        import httpx
        url = f"{base_url.rstrip('/')}{path}"
        headers = {"Content-Type": "application/json"}
        headers.update(self._get_auth_headers())
        try:
            with httpx.Client(timeout=10.0) as client:
                resp = client.post(url, json=data, headers=headers)
                resp.raise_for_status()
                return resp.json()
        except Exception as e:
            logger.debug("POST %s failed: %s", url, e)
            return None

    def _get(self, base_url: str, path: str) -> dict[str, Any] | None:
        """GET from a peer endpoint."""
        import httpx
        url = f"{base_url.rstrip('/')}{path}"
        headers = self._get_auth_headers()
        try:
            with httpx.Client(timeout=10.0) as client:
                resp = client.get(url, headers=headers)
                resp.raise_for_status()
                return resp.json()
        except Exception as e:
            logger.debug("GET %s failed: %s", url, e)
            return None

    # ── Status / serialization ───────────────────────────────────────

    def get_status(self) -> dict[str, Any]:
        """Full cluster status for API responses."""
        with self._peers_lock:
            peers_list = [p.to_dict() for p in self.peers.values()]
        return {
            "enabled": self._enabled,
            "cluster_id": self._cluster_id,
            "instance_id": self._instance_id,
            "node_name": self.node_name,
            "role": self.role.value,
            "peer_count": len(peers_list),
            "online_peers": sum(1 for p in peers_list if p.get("status") in ("online", "degraded")),
            "peers": peers_list,
        }

    def to_dict(self) -> dict[str, Any]:
        return self.get_status()


# ── Module-level singleton ───────────────────────────────────────────────

_network: ClusterNetwork | None = None
_network_lock = threading.Lock()


def get_cluster_network(cfg: dict | None = None) -> ClusterNetwork:
    """Get or create the singleton ClusterNetwork."""
    global _network
    if _network is not None:
        return _network
    with _network_lock:
        if _network is not None:
            return _network
        if cfg is None:
            try:
                from runtime_safety import load_config
                cfg = load_config()
            except Exception:
                cfg = {}
        _network = ClusterNetwork(cfg)
        return _network


def get_cluster_status() -> dict[str, Any]:
    """Quick cluster status check."""
    if _network is None:
        return {"enabled": False, "peer_count": 0}
    return _network.get_status()


def is_cluster_enabled() -> bool:
    """Check if clustering is active."""
    if _network is None:
        return False
    return _network.enabled
