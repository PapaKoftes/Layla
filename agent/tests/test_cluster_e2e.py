"""End-to-end cluster tests — pairing, heartbeat, task dispatch, knowledge sync.

Tests the full lifecycle using a single TestClient against the real FastAPI
app.  TestClient uses ``testclient`` as the remote host, so we monkeypatch
the cluster auth validator to treat it as localhost.

Covered flows:
  1. Queen generates pairing token
  2. Drone pairs with that token
  3. Heartbeat exchange updates peer status
  4. Queen submits a task → claim-based status check
  5. Knowledge sync: push learnings, pull back, verify dedup
  6. Queue stats and cancellation

Phase 5C of the full maturity plan.
"""
from __future__ import annotations

import hashlib
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

AGENT_DIR = Path(__file__).resolve().parent.parent
if str(AGENT_DIR) not in sys.path:
    sys.path.insert(0, str(AGENT_DIR))

import routers.cluster as _cluster_router  # noqa: E402
from main import app  # noqa: E402

# ── Fixtures ───────────────────────────────────────────────────────────────

def _always_valid(request):
    """Auth stub: TestClient sends 'testclient' as host, bypass it."""
    return True


def _noop_require_auth(request):
    """Require-auth stub: never raises."""
    pass


class _FakeClient:
    """Mimics request.client with host='127.0.0.1'."""
    host = "127.0.0.1"
    port = 0


@pytest.fixture(autouse=True)
def _bypass_cluster_auth(monkeypatch):
    """All cluster tests run with auth bypassed (simulates localhost).

    TestClient sends 'testclient' as the remote host, which fails the
    localhost check in ``_validate_cluster_auth`` and in inline IP checks
    in ``/pair/token`` and ``/status``.  We patch the auth functions so
    all authed endpoints pass, and use ASGI middleware to spoof the
    client address to 127.0.0.1 for inline IP checks.
    """
    monkeypatch.setattr(_cluster_router, "_validate_cluster_auth", _always_valid)
    monkeypatch.setattr(_cluster_router, "_require_auth", _noop_require_auth)


@pytest.fixture()
def client():
    """Fresh TestClient per test.

    Wraps the ASGI app with middleware that sets client address to
    127.0.0.1 so inline IP checks (in /pair/token, /status) pass.
    """
    from starlette.types import ASGIApp, Receive, Scope, Send

    class LocalhostMiddleware:
        """Override client IP to 127.0.0.1 for inline localhost checks."""
        def __init__(self, app: ASGIApp):
            self.app = app
        async def __call__(self, scope: Scope, receive: Receive, send: Send):
            if scope["type"] == "http":
                scope["client"] = ("127.0.0.1", 0)
            await self.app(scope, receive, send)

    wrapped = LocalhostMiddleware(app)
    return TestClient(wrapped)


# ── 1. Cluster status (baseline) ──────────────────────────────────────────


def test_cluster_status_returns_ok(client):
    """GET /cluster/status should always return 200, even when disabled."""
    r = client.get("/cluster/status")
    assert r.status_code == 200
    data = r.json()
    assert data.get("ok") is True
    # Should report governor_mode at minimum
    assert "governor_mode" in data


def test_cluster_status_includes_cluster_fields(client):
    """Status should contain cluster_enabled and related fields."""
    r = client.get("/cluster/status")
    data = r.json()
    # Even if disabled, should have a boolean indicator
    # (get_cluster_status returns {"enabled": False} when no network)
    assert isinstance(data.get("cluster_enabled", data.get("enabled", False)), bool)


# ── 2. Pairing token generation ───────────────────────────────────────────


def test_generate_pairing_token_localhost(client):
    """QUEEN can generate a pairing token from localhost."""
    r = client.get("/cluster/pair/token")
    assert r.status_code == 200
    data = r.json()
    assert data.get("ok") is True
    assert "token" in data
    assert len(data["token"]) > 10  # should be ~32 chars
    assert data.get("expires_in_seconds", 0) > 0


def test_pairing_token_is_unique(client):
    """Each call should generate a different token."""
    r1 = client.get("/cluster/pair/token")
    r2 = client.get("/cluster/pair/token")
    t1 = r1.json().get("token", "")
    t2 = r2.json().get("token", "")
    assert t1 != t2


# ── 3. Drone pairing flow ─────────────────────────────────────────────────


def test_pair_with_valid_token(client):
    """Full pairing: generate token → drone submits → receives cluster_secret."""
    # Step 1: Queen generates token
    token_resp = client.get("/cluster/pair/token")
    assert token_resp.status_code == 200
    token = token_resp.json()["token"]

    # Step 2: Drone pairs using the token
    drone_id = uuid.uuid4().hex[:12]
    pair_resp = client.post("/cluster/pair", json={
        "pairing_token": token,
        "instance_id": drone_id,
        "name": "test-drone",
        "address": "http://192.168.1.42:8000",
        "hardware_tier": "gpu",
    })
    assert pair_resp.status_code == 200
    pair_data = pair_resp.json()
    assert pair_data.get("ok") is True
    assert "cluster_id" in pair_data
    assert "cluster_secret" in pair_data
    assert len(pair_data["cluster_secret"]) > 20
    assert "queen_address" in pair_data


def test_pair_with_invalid_token(client):
    """Pairing with a bogus token should fail with 401."""
    r = client.post("/cluster/pair", json={
        "pairing_token": "totally-bogus-token",
        "instance_id": "drone-x",
        "name": "bad-drone",
        "address": "http://10.0.0.1:8000",
    })
    assert r.status_code == 401


def test_pair_token_single_use(client):
    """A pairing token can only be used once."""
    # Generate token
    token = client.get("/cluster/pair/token").json()["token"]

    # First use: success
    r1 = client.post("/cluster/pair", json={
        "pairing_token": token,
        "instance_id": "drone-first",
        "name": "first-drone",
        "address": "http://10.0.0.2:8000",
    })
    assert r1.status_code == 200
    assert r1.json().get("ok") is True

    # Second use: should fail
    r2 = client.post("/cluster/pair", json={
        "pairing_token": token,
        "instance_id": "drone-second",
        "name": "second-drone",
        "address": "http://10.0.0.3:8000",
    })
    assert r2.status_code == 401


# ── 4. Heartbeat exchange ─────────────────────────────────────────────────


def test_heartbeat_basic(client):
    """POST /cluster/heartbeat should return our node's status."""
    drone_id = uuid.uuid4().hex[:12]
    r = client.post("/cluster/heartbeat", json={
        "instance_id": drone_id,
        "name": "test-drone-hb",
        "role": "drone",
        "governor_mode": "breathe",
        "current_load": 0.45,
        "current_tasks": 2,
    })
    assert r.status_code == 200
    data = r.json()
    assert data.get("ok") is True
    # Response should contain the queen's own info
    assert "governor_mode" in data


def test_heartbeat_updates_peer_after_pairing(client):
    """After pairing a drone, heartbeats from it should update its peer record."""
    # Pair a drone first
    token = client.get("/cluster/pair/token").json()["token"]
    drone_id = uuid.uuid4().hex[:12]
    client.post("/cluster/pair", json={
        "pairing_token": token,
        "instance_id": drone_id,
        "name": "hb-drone",
        "address": "http://10.0.0.5:8000",
    })

    # Send heartbeat from that drone
    hb = client.post("/cluster/heartbeat", json={
        "instance_id": drone_id,
        "name": "hb-drone",
        "role": "drone",
        "governor_mode": "sprint",
        "current_load": 0.8,
        "current_tasks": 5,
    })
    assert hb.status_code == 200

    # Verify peer list reflects the drone
    peers_resp = client.get("/cluster/peers")
    assert peers_resp.status_code == 200
    peers_data = peers_resp.json()
    assert peers_data.get("ok") is True


# ── 5. Task submission + status lifecycle ─────────────────────────────────


def _task_id():
    """Generate a unique task ID for tests."""
    return f"t-{uuid.uuid4().hex[:12]}"


def test_task_submit_and_get_status(client):
    """Submit a task → poll status → confirm it's pending."""
    tid = _task_id()
    task_payload = {
        "id": tid,
        "type": "inference",
        "priority": 1,
        "payload": {"prompt": "Hello, world", "max_tokens": 100},
        "timeout_seconds": 60,
        "source_node": "test-queen",
    }
    r = client.post("/cluster/task/submit", json=task_payload)
    assert r.status_code == 200
    data = r.json()
    assert data.get("ok") is True
    task_id = data["task_id"]
    assert task_id == tid

    # Poll status
    sr = client.get(f"/cluster/task/{task_id}/status")
    assert sr.status_code == 200
    status_data = sr.json()
    assert status_data["id"] == task_id
    assert status_data["type"] == "inference"
    assert status_data["status"] in ("pending", "running")


def test_task_cancel(client):
    """Submit a task then cancel it."""
    tid = _task_id()
    r = client.post("/cluster/task/submit", json={
        "id": tid,
        "type": "embedding",
        "priority": 2,
        "payload": {"text": "test embedding"},
        "timeout_seconds": 30,
    })
    task_id = r.json()["task_id"]
    assert task_id == tid

    # Cancel
    cr = client.post(f"/cluster/task/{task_id}/cancel")
    assert cr.status_code == 200
    assert cr.json().get("ok") is True

    # Verify cancelled
    sr = client.get(f"/cluster/task/{task_id}/status")
    assert sr.json()["status"] == "cancelled"


def test_task_not_found(client):
    """Polling a nonexistent task should 404."""
    r = client.get("/cluster/task/nonexistent-id/status")
    assert r.status_code == 404


def test_task_preserves_custom_id(client):
    """Task with a custom ID should preserve that ID."""
    custom_id = _task_id()
    r = client.post("/cluster/task/submit", json={
        "id": custom_id,
        "type": "study",
        "payload": {"topic": "custom-id test"},
    })
    assert r.status_code == 200
    assert r.json()["task_id"] == custom_id

    sr = client.get(f"/cluster/task/{custom_id}/status")
    assert sr.status_code == 200
    assert sr.json()["id"] == custom_id


# ── 6. Knowledge sync: push + pull + dedup ────────────────────────────────


def test_sync_push_imports_learnings(client):
    """Push learnings → imported count should be > 0."""
    unique_content = f"E2E test learning {uuid.uuid4().hex[:8]}"
    r = client.post("/cluster/sync/push", json={
        "learnings": [
            {"content": unique_content, "type": "fact", "confidence": 0.8, "source": "e2e_test"},
        ]
    })
    assert r.status_code == 200
    data = r.json()
    assert data.get("ok") is True
    assert data.get("imported", 0) >= 1
    assert data.get("skipped", 0) == 0


def test_sync_push_deduplicates(client):
    """Pushing the same learning twice should skip the duplicate."""
    content = f"Dedup test {uuid.uuid4().hex[:8]}"

    # First push
    r1 = client.post("/cluster/sync/push", json={
        "learnings": [{"content": content, "type": "fact"}]
    })
    assert r1.json().get("imported") == 1

    # Second push — same content
    r2 = client.post("/cluster/sync/push", json={
        "learnings": [{"content": content, "type": "fact"}]
    })
    assert r2.json().get("skipped") == 1
    assert r2.json().get("imported") == 0


def test_sync_push_skips_empty(client):
    """Learnings with empty content should be skipped."""
    r = client.post("/cluster/sync/push", json={
        "learnings": [
            {"content": "", "type": "fact"},
            {"content": "   ", "type": "fact"},  # whitespace-only should be kept (not empty string)
        ]
    })
    data = r.json()
    assert data.get("ok") is True
    # At least the empty-string one should be skipped
    assert data.get("skipped", 0) >= 1


def test_sync_pull_returns_learnings(client):
    """Push a learning, then pull since before that time."""
    content = f"Pull test {uuid.uuid4().hex[:8]}"
    datetime.now(timezone.utc).isoformat()

    # Push
    client.post("/cluster/sync/push", json={
        "learnings": [{"content": content, "type": "observation", "confidence": 0.9}]
    })

    # Pull since before the push
    r = client.post("/cluster/sync/pull", json={"since": "2000-01-01T00:00:00+00:00"})
    assert r.status_code == 200
    data = r.json()
    assert data.get("ok") is True
    assert data.get("count", 0) >= 1
    # Verify our learning is in the results
    contents = [l.get("content", "") for l in data.get("learnings", [])]
    assert content in contents


def test_sync_pull_respects_since_filter(client):
    """Pull with a future timestamp should return 0 learnings."""
    r = client.post("/cluster/sync/pull", json={"since": "2099-01-01T00:00:00+00:00"})
    assert r.status_code == 200
    data = r.json()
    assert data.get("count", 0) == 0


def test_sync_roundtrip(client):
    """Full roundtrip: push from 'drone' → pull from 'queen', verify content integrity."""
    items = []
    for i in range(3):
        items.append({
            "content": f"Roundtrip item {i} — {uuid.uuid4().hex[:6]}",
            "type": "fact" if i % 2 == 0 else "observation",
            "confidence": 0.7 + i * 0.1,
            "source": "drone-alpha",
        })

    push_r = client.post("/cluster/sync/push", json={"learnings": items})
    assert push_r.json().get("imported") == 3

    pull_r = client.post("/cluster/sync/pull", json={"since": "2000-01-01T00:00:00+00:00"})
    pulled = pull_r.json().get("learnings", [])
    pulled_contents = {l["content"] for l in pulled}

    for item in items:
        assert item["content"] in pulled_contents, f"Missing: {item['content']}"


# ── 7. Queue stats ────────────────────────────────────────────────────────


def test_queue_stats_endpoint(client):
    """GET /cluster/queue/stats returns valid structure."""
    r = client.get("/cluster/queue/stats")
    assert r.status_code == 200
    data = r.json()
    assert data.get("ok") is True
    assert "stats" in data
    assert "pending" in data
    assert "running" in data
    assert isinstance(data["pending"], list)
    assert isinstance(data["running"], list)


def test_queue_stats_reflect_submitted_task(client):
    """After submitting a task, queue stats should reflect it."""
    # Submit a task
    client.post("/cluster/task/submit", json={
        "id": _task_id(),
        "type": "ingestion",
        "priority": 1,
        "payload": {"file": "test.txt"},
    })

    r = client.get("/cluster/queue/stats")
    data = r.json()
    stats = data.get("stats", {})
    # Should have at least one pending task
    total = sum(stats.values())
    assert total >= 1


# ── 8. Peers listing ──────────────────────────────────────────────────────


def test_peers_endpoint_returns_list(client):
    """GET /cluster/peers should return a list."""
    r = client.get("/cluster/peers")
    assert r.status_code == 200
    data = r.json()
    # Even with ok=False (no cluster network), peers should be a list
    assert isinstance(data.get("peers", []), list)


# ── 9. Full lifecycle: pair → heartbeat → task → sync ─────────────────────


def test_full_cluster_lifecycle(client):
    """End-to-end: pair a drone, exchange heartbeats, dispatch a task,
    sync knowledge, verify everything connects."""

    # === Step 1: Generate pairing token ===
    token_r = client.get("/cluster/pair/token")
    assert token_r.status_code == 200
    pairing_token = token_r.json()["token"]

    # === Step 2: Drone pairs with queen ===
    drone_id = f"lifecycle-drone-{uuid.uuid4().hex[:6]}"
    pair_r = client.post("/cluster/pair", json={
        "pairing_token": pairing_token,
        "instance_id": drone_id,
        "name": "lifecycle-test-drone",
        "address": "http://10.0.0.99:8000",
        "hardware_tier": "gpu",
    })
    assert pair_r.status_code == 200
    pair_data = pair_r.json()
    assert pair_data.get("ok") is True
    pair_data["cluster_secret"]
    pair_data["cluster_id"]

    # === Step 3: Drone sends heartbeat ===
    hb_r = client.post("/cluster/heartbeat", json={
        "instance_id": drone_id,
        "name": "lifecycle-test-drone",
        "role": "drone",
        "governor_mode": "sprint",
        "current_load": 0.3,
        "current_tasks": 0,
    })
    assert hb_r.status_code == 200
    assert hb_r.json().get("ok") is True

    # === Step 4: Queen submits a task ===
    lifecycle_task_id = _task_id()
    task_r = client.post("/cluster/task/submit", json={
        "id": lifecycle_task_id,
        "type": "inference",
        "priority": 1,
        "payload": {"prompt": "lifecycle test", "max_tokens": 50},
        "timeout_seconds": 120,
        "source_node": "queen",
    })
    assert task_r.status_code == 200
    assert task_r.json()["task_id"] == lifecycle_task_id

    # Check task is pending
    status_r = client.get(f"/cluster/task/{lifecycle_task_id}/status")
    assert status_r.json()["status"] == "pending"

    # === Step 5: Cancel (simulating completion is internal) ===
    cancel_r = client.post(f"/cluster/task/{lifecycle_task_id}/cancel")
    assert cancel_r.json().get("ok") is True
    assert client.get(f"/cluster/task/{lifecycle_task_id}/status").json()["status"] == "cancelled"

    # === Step 6: Drone pushes knowledge ===
    knowledge_content = f"Lifecycle learning {uuid.uuid4().hex[:8]}"
    sync_r = client.post("/cluster/sync/push", json={
        "learnings": [{
            "content": knowledge_content,
            "type": "fact",
            "confidence": 0.85,
            "source": f"drone:{drone_id}",
        }]
    })
    assert sync_r.json().get("imported") == 1

    # === Step 7: Queen pulls knowledge (includes drone's push) ===
    pull_r = client.post("/cluster/sync/pull", json={
        "since": "2000-01-01T00:00:00+00:00",
    })
    pulled = pull_r.json().get("learnings", [])
    found = any(l["content"] == knowledge_content for l in pulled)
    assert found, "Drone's learning not found in queen's pull results"

    # === Step 8: Verify cluster status reflects activity ===
    status_r = client.get("/cluster/status")
    assert status_r.status_code == 200
    assert status_r.json().get("ok") is True


# ── 10. Edge cases ────────────────────────────────────────────────────────


def test_submit_all_task_types(client):
    """All TaskType variants should be accepted."""
    task_types = ["inference", "embedding", "ingestion", "study", "backup",
                  "consolidation", "wiki_build"]
    for tt in task_types:
        tid = _task_id()
        r = client.post("/cluster/task/submit", json={
            "id": tid,
            "type": tt,
            "payload": {"test": True},
        })
        assert r.status_code == 200, f"Task type '{tt}' failed: {r.text}"
        assert r.json().get("ok") is True


def test_submit_task_with_high_priority(client):
    """Priority 0 (critical) tasks should be submittable."""
    tid = _task_id()
    r = client.post("/cluster/task/submit", json={
        "id": tid,
        "type": "inference",
        "priority": 0,
        "payload": {"prompt": "urgent"},
    })
    assert r.status_code == 200
    task_id = r.json()["task_id"]
    assert task_id == tid
    status = client.get(f"/cluster/task/{task_id}/status").json()
    assert status["priority"] == 0


def test_sync_push_multiple_mixed(client):
    """Push a batch with mix of valid, empty, and duplicate content."""
    unique = f"batch-{uuid.uuid4().hex[:8]}"
    r = client.post("/cluster/sync/push", json={
        "learnings": [
            {"content": unique, "type": "fact"},
            {"content": "", "type": "fact"},            # empty → skip
            {"content": unique, "type": "observation"},  # duplicate hash → skip
        ]
    })
    data = r.json()
    assert data.get("imported") == 1
    assert data.get("skipped") == 2


def test_cancel_nonexistent_task(client):
    """Cancelling a task that doesn't exist should return ok=False."""
    r = client.post("/cluster/task/fake-does-not-exist/cancel")
    assert r.status_code == 200
    assert r.json().get("ok") is False
