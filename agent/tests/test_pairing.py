"""Tests for Phase 9.2: Device pairing router."""

import json
import time
from pathlib import Path
from unittest.mock import patch

import pytest

# Minimal app for testing the pairing router
from fastapi import FastAPI
from fastapi.testclient import TestClient

from routers.pairing import (
    _PAIRED_DEVICES_FILE,
    _PAIRING_LOCK,
    _generate_pin,
    _generate_shared_secret,
    _load_paired_devices,
    _pending_pairings,
    _save_paired_devices,
    router,
)

app = FastAPI()
app.include_router(router)
client = TestClient(app)


# ── Unit tests ───────────────────────────────────────────────────────────────

def test_generate_pin_format():
    """PIN must be exactly 6 digits."""
    for _ in range(20):
        pin = _generate_pin()
        assert len(pin) == 6
        assert pin.isdigit()


def test_generate_pin_uniqueness():
    """PINs should be unique (statistically)."""
    pins = {_generate_pin() for _ in range(50)}
    assert len(pins) > 40  # At least 80% unique out of 50


def test_generate_shared_secret_length():
    """Shared secret must be a hex string of sufficient length."""
    secret = _generate_shared_secret()
    assert len(secret) == 64  # 32 bytes = 64 hex chars
    assert all(c in "0123456789abcdef" for c in secret)


def test_generate_shared_secret_uniqueness():
    """Shared secrets must be unique."""
    secrets = {_generate_shared_secret() for _ in range(20)}
    assert len(secrets) == 20


# ── Endpoint tests ───────────────────────────────────────────────────────────

def test_list_peers_empty():
    """GET /pairing/peers returns list (possibly empty)."""
    with patch("routers.pairing.logger"):
        r = client.get("/pairing/peers")
    assert r.status_code == 200
    assert isinstance(r.json(), list)


def test_discovery_status():
    """GET /pairing/status returns valid structure."""
    r = client.get("/pairing/status")
    assert r.status_code == 200
    data = r.json()
    assert "enabled" in data
    assert "instance_id" in data
    assert "peer_count" in data


def test_start_discovery():
    """POST /pairing/start returns ok field."""
    r = client.post("/pairing/start")
    assert r.status_code == 200
    data = r.json()
    assert "ok" in data


def test_stop_discovery():
    """POST /pairing/stop returns ok field."""
    r = client.post("/pairing/stop")
    assert r.status_code == 200
    data = r.json()
    assert "ok" in data


def test_initiate_pairing():
    """POST /pairing/pair generates a PIN."""
    r = client.post("/pairing/pair", json={
        "instance_id": "test-instance-123",
        "device_name": "TestDevice",
    })
    assert r.status_code == 200
    data = r.json()
    assert data["ok"] is True
    assert data["pin"] is not None
    assert len(data["pin"]) == 6
    assert data["ttl_seconds"] > 0
    # Clean up pending
    with _PAIRING_LOCK:
        _pending_pairings.pop(data["pin"], None)


def test_initiate_pairing_no_instance_id():
    """POST /pairing/pair without instance_id returns 400."""
    r = client.post("/pairing/pair", json={"instance_id": ""})
    assert r.status_code == 400


def test_confirm_pairing_invalid_pin():
    """POST /pairing/confirm with bad PIN returns error."""
    r = client.post("/pairing/confirm", json={
        "pin": "999999",
        "instance_id": "fake-id",
    })
    assert r.status_code == 200
    data = r.json()
    assert data["ok"] is False
    assert "invalid" in data.get("error", "").lower() or "expired" in data.get("error", "").lower()


def test_full_pairing_flow(tmp_path):
    """Full pair → confirm → list → unpair flow."""
    # Override paired devices file for isolation
    fake_file = tmp_path / "paired_devices.json"
    with patch("routers.pairing._PAIRED_DEVICES_FILE", fake_file):
        # Step 1: Initiate
        r = client.post("/pairing/pair", json={
            "instance_id": "flow-test-peer",
            "device_name": "FlowTestDevice",
        })
        assert r.status_code == 200
        pin = r.json()["pin"]

        # Step 2: Confirm with correct PIN
        r = client.post("/pairing/confirm", json={
            "pin": pin,
            "instance_id": "flow-test-peer",
        })
        assert r.status_code == 200
        assert r.json()["ok"] is True

        # Step 3: List paired devices
        r = client.get("/pairing/paired-devices")
        assert r.status_code == 200
        devices = r.json()
        ids = [d["instance_id"] for d in devices]
        assert "flow-test-peer" in ids

        # Step 4: Unpair
        r = client.delete("/pairing/flow-test-peer")
        assert r.status_code == 200
        assert r.json()["ok"] is True

        # Step 5: Verify removed
        r = client.get("/pairing/paired-devices")
        ids = [d["instance_id"] for d in r.json()]
        assert "flow-test-peer" not in ids


def test_confirm_wrong_instance_id():
    """Confirm with correct PIN but wrong instance_id fails."""
    # Create a pending pairing
    r = client.post("/pairing/pair", json={
        "instance_id": "correct-peer",
        "device_name": "CorrectPeer",
    })
    pin = r.json()["pin"]

    # Try confirm with wrong instance_id
    r = client.post("/pairing/confirm", json={
        "pin": pin,
        "instance_id": "wrong-peer",
    })
    data = r.json()
    assert data["ok"] is False
    assert "match" in data.get("error", "").lower() or "not" in data.get("error", "").lower()

    # Clean up
    with _PAIRING_LOCK:
        _pending_pairings.pop(pin, None)


def test_unpair_nonexistent():
    """DELETE /pairing/{id} for unknown device returns error."""
    r = client.delete("/pairing/nonexistent-id-12345")
    assert r.status_code == 200
    data = r.json()
    assert data["ok"] is False


def test_peer_health_not_found():
    """GET /pairing/peer/{id}/health for unknown peer returns not found."""
    r = client.get("/pairing/peer/unknown-peer-xyz/health")
    assert r.status_code == 200
    data = r.json()
    assert data["reachable"] is False


def test_refresh_peers():
    """POST /pairing/refresh returns ok and peer_count."""
    r = client.post("/pairing/refresh")
    assert r.status_code == 200
    data = r.json()
    assert "ok" in data
    assert "peer_count" in data


def test_paired_devices_list_empty():
    """GET /pairing/paired-devices returns list."""
    r = client.get("/pairing/paired-devices")
    assert r.status_code == 200
    assert isinstance(r.json(), list)
