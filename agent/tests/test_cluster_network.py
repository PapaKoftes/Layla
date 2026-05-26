"""Tests for services.cluster_network — peer management, heartbeat, discovery."""
from __future__ import annotations

import sys
import time
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from services.cluster_network import (
    ClusterNetwork,
    Peer,
    PeerStatus,
    NodeRole,
    load_cluster_config,
    save_cluster_config,
    CLUSTER_CONFIG_FILE,
)


@pytest.fixture
def cfg():
    return {
        "cluster_enabled": True,
        "node_role": "queen",
        "cluster_heartbeat_interval": 30,
        "cluster_task_timeout": 300,
        "cluster_sync_interval": 300,
    }


@pytest.fixture
def network(cfg, tmp_path, monkeypatch):
    """Create a ClusterNetwork with a temporary config file."""
    config_file = tmp_path / "cluster_config.json"
    config_file.write_text('{"cluster_enabled": true, "node_role": "queen", "cluster_id": "test-cluster-123", "cluster_secret_hash": "", "peers": {}}')
    monkeypatch.setattr("services.cluster_network.CLUSTER_CONFIG_FILE", config_file)
    # Provide a stable instance ID
    monkeypatch.setattr("services.cluster_network.ClusterNetwork.__init__", _patched_init(cfg, config_file))
    net = ClusterNetwork.__new__(ClusterNetwork)
    _patched_init(cfg, config_file)(net, cfg)
    return net


def _patched_init(cfg, config_file):
    """Build a patched __init__ that avoids mDNS import."""
    import json
    import threading
    import uuid

    def init(self, cfg):
        self._cfg = cfg
        self._cluster_config = json.loads(config_file.read_text())
        self.role = NodeRole(cfg.get("node_role", "queen"))
        self._node_name = "test-queen"
        self._cluster_id = self._cluster_config.get("cluster_id", "test")
        self._instance_id = "test-queen-id-001"
        self.peers = {}
        self._peers_lock = threading.RLock()
        self._heartbeat_interval = 30
        self._heartbeat_thread = None
        self._stop_event = threading.Event()
        self._http_client = None
        self._enabled = True
    return init


class TestPeerManagement:
    def test_add_peer(self, network):
        peer = Peer(instance_id="drone-001", name="Laptop", role=NodeRole.DRONE)
        network.add_peer(peer)
        assert "drone-001" in network.peers
        assert network.peers["drone-001"].name == "Laptop"

    def test_remove_peer(self, network):
        peer = Peer(instance_id="drone-002", name="Laptop2", role=NodeRole.DRONE)
        network.add_peer(peer)
        assert network.remove_peer("drone-002") is True
        assert "drone-002" not in network.peers

    def test_remove_nonexistent(self, network):
        assert network.remove_peer("ghost") is False

    def test_get_online_peers(self, network):
        network.add_peer(Peer(instance_id="d1", status=PeerStatus.ONLINE))
        network.add_peer(Peer(instance_id="d2", status=PeerStatus.OFFLINE))
        network.add_peer(Peer(instance_id="d3", status=PeerStatus.DEGRADED))
        online = network.get_online_peers()
        assert len(online) == 2
        ids = {p.instance_id for p in online}
        assert ids == {"d1", "d3"}

    def test_get_online_drones(self, network):
        network.add_peer(Peer(instance_id="d1", role=NodeRole.DRONE, status=PeerStatus.ONLINE))
        network.add_peer(Peer(instance_id="q1", role=NodeRole.QUEEN, status=PeerStatus.ONLINE))
        drones = network.get_online_drones()
        assert len(drones) == 1
        assert drones[0].instance_id == "d1"


class TestPeerDataclass:
    def test_peer_to_dict(self):
        p = Peer(instance_id="abc", name="Test", role=NodeRole.DRONE, status=PeerStatus.ONLINE)
        d = p.to_dict()
        assert d["role"] == "drone"
        assert d["status"] == "online"
        assert d["instance_id"] == "abc"

    def test_peer_from_dict(self):
        d = {"instance_id": "xyz", "name": "Remote", "role": "queen", "status": "degraded"}
        p = Peer.from_dict(d)
        assert p.instance_id == "xyz"
        assert p.role == NodeRole.QUEEN
        assert p.status == PeerStatus.DEGRADED

    def test_peer_is_online(self):
        assert Peer(instance_id="x", status=PeerStatus.ONLINE).is_online() is True
        assert Peer(instance_id="x", status=PeerStatus.DEGRADED).is_online() is True
        assert Peer(instance_id="x", status=PeerStatus.OFFLINE).is_online() is False

    def test_peer_has_capability(self):
        p = Peer(instance_id="x", capabilities=["inference", "embedding"])
        assert p.has_capability("inference") is True
        assert p.has_capability("backup") is False

    def test_peer_no_capabilities_means_all(self):
        p = Peer(instance_id="x", capabilities=[])
        assert p.has_capability("anything") is True


class TestClusterStatus:
    def test_get_status(self, network):
        network.add_peer(Peer(instance_id="d1", status=PeerStatus.ONLINE))
        network.add_peer(Peer(instance_id="d2", status=PeerStatus.OFFLINE))
        status = network.get_status()
        assert status["enabled"] is True
        assert status["role"] == "queen"
        assert status["peer_count"] == 2
        assert status["online_peers"] == 1

    def test_instance_id(self, network):
        assert network.instance_id == "test-queen-id-001"


class TestHeartbeatLoop:
    def test_check_peer_health_demotes(self, network):
        """Peers that miss heartbeats get demoted."""
        old_time = time.time() - 200  # 200 seconds ago
        network.add_peer(Peer(
            instance_id="stale",
            status=PeerStatus.ONLINE,
            last_heartbeat=old_time,
        ))
        network._check_peer_health()
        assert network.peers["stale"].status == PeerStatus.OFFLINE

    def test_check_peer_health_degrades(self, network):
        """Peer missing one heartbeat becomes DEGRADED."""
        recent = time.time() - 100  # Within degraded window (>90s, <180s for 30s interval)
        network.add_peer(Peer(
            instance_id="recent",
            status=PeerStatus.ONLINE,
            last_heartbeat=recent,
        ))
        network._check_peer_health()
        assert network.peers["recent"].status == PeerStatus.DEGRADED

    def test_start_stop_heartbeat(self, network):
        """Heartbeat thread starts and stops cleanly."""
        network.start_heartbeat()
        assert network._heartbeat_thread is not None
        assert network._heartbeat_thread.is_alive()
        network.stop_heartbeat()
        assert not network._heartbeat_thread or not network._heartbeat_thread.is_alive()


class TestNodeRole:
    def test_role_enum(self):
        assert NodeRole.QUEEN.value == "queen"
        assert NodeRole.DRONE.value == "drone"
        assert NodeRole("queen") == NodeRole.QUEEN

    def test_network_role(self, network):
        assert network.role == NodeRole.QUEEN
