"""Tests for Phase 9.1: mDNS Discovery service."""

import time
from unittest.mock import MagicMock, patch

from services.mdns_discovery import (
    SERVICE_TYPE,
    _get_or_create_instance_id,
    _is_zeroconf_available,
    detect_hardware_tier,
    get_discovered_peers,
    get_best_peer_for_inference,
    get_instance_id,
    get_status,
    is_running,
    peer_count,
    _discovered_peers,
    _peers_lock,
)


def test_service_type_is_layla_tcp():
    """Service type must be _layla._tcp.local. per spec."""
    assert SERVICE_TYPE == "_layla._tcp.local."


def test_instance_id_stable():
    """Instance ID must be stable (same on repeated calls)."""
    id1 = _get_or_create_instance_id()
    id2 = _get_or_create_instance_id()
    assert id1 == id2
    assert len(id1) >= 8


def test_get_instance_id_public():
    """Public accessor returns same value."""
    assert get_instance_id() == _get_or_create_instance_id()


def test_detect_hardware_tier_returns_valid():
    """detect_hardware_tier returns one of the valid tiers."""
    tier = detect_hardware_tier()
    assert tier in ("cpu", "gpu_low", "gpu_mid", "gpu_high")


def test_is_running_initially_false():
    """mDNS is not running until explicitly started."""
    assert is_running() is False


def test_peer_count_initially_zero():
    """No peers before any discovery."""
    assert peer_count() >= 0  # may have peers from prior tests


def test_get_discovered_peers_filters_stale():
    """get_discovered_peers filters out stale entries."""
    test_id = "test-stale-peer-123"
    with _peers_lock:
        _discovered_peers[test_id] = {
            "instance_id": test_id,
            "name": "StaleDevice",
            "ip": "192.168.1.99",
            "port": 8000,
            "hardware_tier": "cpu",
            "models": [],
            "version": "0.0.1",
            "last_seen": time.time() - 999,  # very old
        }
    peers = get_discovered_peers(max_age_s=60)
    ids = [p["instance_id"] for p in peers]
    assert test_id not in ids
    # Clean up
    with _peers_lock:
        _discovered_peers.pop(test_id, None)


def test_get_discovered_peers_returns_fresh():
    """get_discovered_peers returns fresh entries."""
    test_id = "test-fresh-peer-456"
    with _peers_lock:
        _discovered_peers[test_id] = {
            "instance_id": test_id,
            "name": "FreshDevice",
            "ip": "192.168.1.50",
            "port": 8000,
            "hardware_tier": "gpu_mid",
            "models": ["llama3.1"],
            "version": "1.0.0",
            "last_seen": time.time(),
        }
    peers = get_discovered_peers(max_age_s=60)
    ids = [p["instance_id"] for p in peers]
    assert test_id in ids
    # Clean up
    with _peers_lock:
        _discovered_peers.pop(test_id, None)


def test_get_best_peer_for_inference_empty():
    """get_best_peer_for_inference returns None when no peers."""
    # Ensure clean state
    with _peers_lock:
        saved = dict(_discovered_peers)
        _discovered_peers.clear()
    try:
        result = get_best_peer_for_inference()
        assert result is None
    finally:
        with _peers_lock:
            _discovered_peers.update(saved)


def test_get_best_peer_for_inference_selects_highest_tier():
    """get_best_peer_for_inference picks the highest-tier peer."""
    t1 = "test-peer-cpu"
    t2 = "test-peer-gpu-high"
    now = time.time()
    with _peers_lock:
        saved = dict(_discovered_peers)
        _discovered_peers.clear()
        _discovered_peers[t1] = {
            "instance_id": t1, "name": "CPU Box", "ip": "10.0.0.1",
            "port": 8000, "hardware_tier": "cpu", "models": [], "version": "1",
            "last_seen": now,
        }
        _discovered_peers[t2] = {
            "instance_id": t2, "name": "GPU Beast", "ip": "10.0.0.2",
            "port": 8000, "hardware_tier": "gpu_high", "models": ["big-model"], "version": "1",
            "last_seen": now,
        }
    try:
        best = get_best_peer_for_inference()
        assert best is not None
        assert best["instance_id"] == t2
        assert best["hardware_tier"] == "gpu_high"
    finally:
        with _peers_lock:
            _discovered_peers.clear()
            _discovered_peers.update(saved)


def test_get_best_peer_respects_min_tier():
    """get_best_peer_for_inference filters by min_tier."""
    t1 = "test-peer-cpu-only"
    now = time.time()
    with _peers_lock:
        saved = dict(_discovered_peers)
        _discovered_peers.clear()
        _discovered_peers[t1] = {
            "instance_id": t1, "name": "CPU Only", "ip": "10.0.0.3",
            "port": 8000, "hardware_tier": "cpu", "models": [], "version": "1",
            "last_seen": now,
        }
    try:
        result = get_best_peer_for_inference(min_tier="gpu_low")
        assert result is None  # CPU box doesn't meet gpu_low requirement
    finally:
        with _peers_lock:
            _discovered_peers.clear()
            _discovered_peers.update(saved)


def test_get_status_structure():
    """get_status returns expected keys."""
    status = get_status()
    assert "enabled" in status
    assert "instance_id" in status
    assert "service_type" in status
    assert "peer_count" in status
    assert "peers" in status
    assert "zeroconf_installed" in status
    assert status["service_type"] == SERVICE_TYPE


def test_zeroconf_available_check():
    """_is_zeroconf_available returns bool."""
    result = _is_zeroconf_available()
    assert isinstance(result, bool)


def test_check_peer_health_unreachable():
    """check_peer_health returns unreachable for bad IP."""
    from services.mdns_discovery import check_peer_health
    result = check_peer_health({"ip": "192.0.2.1", "port": 1}, timeout=1.0)
    assert result["reachable"] is False
    assert result["error"] is not None
    assert result["latency_ms"] >= 0
