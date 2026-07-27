"""Tests for Plan Item 17 — node-to-node knowledge sync.

Covers the four contract points:
  (a) export + import of learnings AND memories/wiki dedups by content-hash and
      advances a per-peer watermark so re-sync is incremental (not full-resend);
  (b) auto-enable follows a successful pair — pairing turns sync on and PERSISTS it;
  (c) an unpaired / unauthenticated peer is refused;
  (d) sync is a complete no-op when not paired.

All DB access runs against an isolated temp DB (``isolated_db``); every peer /
network / config touch is mocked — no real network, no real config files.
"""
from __future__ import annotations

import types
from unittest.mock import MagicMock, patch

import pytest

from services.cluster import node_sync as ns

# Controlled ISO timestamps (sort lexicographically, which is how the watermark compares).
T1 = "2026-01-01T00:00:00+00:00"
T2 = "2026-02-01T00:00:00+00:00"
T3 = "2026-03-01T00:00:00+00:00"
EPOCH = "2000-01-01T00:00:00Z"


def _records(kind: str, contents_and_times):
    """Build wire records for a kind (content_hash left out — import computes it)."""
    out = []
    for content, created in contents_and_times:
        rec = {"kind": kind, "content": content, "created_at": created}
        if kind == "memory":
            rec["aspect_id"] = "morrigan"
        elif kind == "knowledge":
            rec["title"] = "note"
            rec["tags"] = "wiki"
        out.append(rec)
    return out


# ── (a) export/import round-trip: dedup + incremental watermark ──────────────

@pytest.mark.parametrize("kind", ["learning", "memory", "knowledge"])
def test_import_dedups_and_watermark_is_incremental(isolated_db, kind):
    """import inserts new records, a re-import is fully skipped (content-hash dedup),
    and after advancing the watermark an export returns ONLY the newer record."""
    c1 = f"{kind}: first canonical fact about the cluster"
    c2 = f"{kind}: second canonical fact about the cluster"
    c3 = f"{kind}: third and newest fact about the cluster"

    first_batch = _records(kind, [(c1, T1), (c2, T2)])

    # First import writes both rows.
    counts = ns.import_records(kind, first_batch, source_label="peerA")
    assert counts["imported"] == 2, counts
    assert counts["skipped"] == 0, counts

    # Re-import of the identical batch is fully deduped — never double-imports.
    counts2 = ns.import_records(kind, first_batch, source_label="peerA")
    assert counts2["imported"] == 0, counts2
    assert counts2["skipped"] == 2, counts2

    # Export from EPOCH sees the round-tripped rows.
    exported = ns.export_since(kind, EPOCH)
    seen = {r["content"] for r in exported}
    assert {c1, c2} <= seen
    # every exported record carries a content hash usable as the dedup key
    for r in exported:
        assert r["content_hash"] == ns._content_hash(r["content"])

    # Advance the per-peer, per-kind PULL watermark to the newest row we've seen.
    peer = "peerA-instance"
    slot = f"{kind}:pull"
    assert ns._get_last_sync_time(peer, slot) == EPOCH  # default before any advance
    ns._advance_watermark(peer, slot, first_batch)
    assert ns._get_last_sync_time(peer, slot) == T2  # advanced to max(created_at)

    # A newer record arrives; export since the watermark returns ONLY it (incremental).
    ns.import_records(kind, _records(kind, [(c3, T3)]), source_label="peerA")
    incremental = ns.export_since(kind, ns._get_last_sync_time(peer, slot))
    inc_contents = {r["content"] for r in incremental}
    assert c3 in inc_contents
    assert c1 not in inc_contents and c2 not in inc_contents


def test_export_import_is_per_kind_isolated(isolated_db):
    """learnings, memories and wiki entries live in different tables — a memory
    is not confused with a learning even with identical text."""
    same = "identical text stored in three different stores"
    for kind in ("learning", "memory", "knowledge"):
        assert ns.import_records(kind, _records(kind, [(same, T1)]))["imported"] == 1

    for kind in ("learning", "memory", "knowledge"):
        contents = {r["content"] for r in ns.export_since(kind, EPOCH)}
        assert same in contents


def test_sync_push_pull_endpoints_roundtrip(isolated_db):
    """The /cluster/sync/push + /pull endpoints carry all three kinds and dedup
    (localhost auth bypass; no network)."""
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from routers import cluster as cluster_router

    app = FastAPI()
    app.include_router(cluster_router.router)
    # Present as localhost so _validate_cluster_auth's localhost bypass applies.
    client = TestClient(app, client=("127.0.0.1", 50000))

    payload = {
        "records": {
            "learning": _records("learning", [("endpoint learning fact", T1)]),
            "memory": _records("memory", [("endpoint memory note", T1)]),
            "knowledge": _records("knowledge", [("endpoint wiki entry", T1)]),
        }
    }
    r = client.post("/cluster/sync/push", json=payload)
    assert r.status_code == 200, r.text
    assert r.json()["imported"] == 3, r.json()

    # Second push is fully deduped.
    r2 = client.post("/cluster/sync/push", json=payload)
    assert r2.json()["imported"] == 0
    assert r2.json()["skipped"] == 3

    # Pull all three kinds back.
    r3 = client.post("/cluster/sync/pull", json={
        "kinds": ["learning", "memory", "knowledge"],
        "since": EPOCH,
    })
    assert r3.status_code == 200, r3.text
    body = r3.json()
    records = body["records"]
    assert {rr["content"] for rr in records["learning"]} >= {"endpoint learning fact"}
    assert {rr["content"] for rr in records["memory"]} >= {"endpoint memory note"}
    assert {rr["content"] for rr in records["knowledge"]} >= {"endpoint wiki entry"}
    # Legacy flat field still present for older peers.
    assert any(rr["content"] == "endpoint learning fact" for rr in body["learnings"])


# ── (b) pairing auto-enables sync + persists ────────────────────────────────

def test_pairing_auto_enables_and_persists(monkeypatch):
    """A successful accept_drone turns clustering ON: it persists cluster_enabled
    into BOTH the cluster config and the RUNTIME config (which startup reads),
    and brings the live subsystem up."""
    # Let the activation body actually run (it is a deliberate no-op under the harness).
    monkeypatch.delenv("LAYLA_MINIMAL_STARTUP", raising=False)

    saved = {}

    def _fake_load():
        return {}

    def _fake_save(cfg):
        saved.clear()
        saved.update(cfg)

    save_config_keys = MagicMock(return_value=["cluster_enabled", "node_role"])
    fake_net = MagicMock()
    fake_net.enabled = False  # keep activation from starting real threads

    with patch("services.cluster.cluster_network.load_cluster_config", _fake_load), \
         patch("services.cluster.cluster_network.save_cluster_config", _fake_save), \
         patch("services.cluster.cluster_network.get_cluster_network", return_value=fake_net), \
         patch("runtime_safety.save_config_keys", save_config_keys):
        from services.cluster.cluster_pairing import ClusterPairing
        result = ClusterPairing().accept_drone(
            drone_instance_id="drone-xyz",
            drone_name="test-drone",
            drone_address="http://10.0.0.9:8000",
        )

    assert result["ok"] is True
    assert len(result["cluster_secret"]) > 20

    # Persisted into cluster_config.json shape.
    assert saved.get("cluster_enabled") is True
    assert saved.get("node_role") == "queen"
    assert "drone-xyz" in saved.get("peers", {})
    assert saved.get("cluster_secret_hash")  # a shared secret now exists

    # Persisted into the RUNTIME config that main.py + ClusterNetwork actually read.
    save_config_keys.assert_called_once()
    args, kwargs = save_config_keys.call_args
    assert args[0].get("cluster_enabled") is True
    assert args[0].get("node_role") == "queen"
    assert kwargs.get("editable_only") is False


def test_activation_is_noop_under_test_harness(monkeypatch):
    """Safety: with LAYLA_MINIMAL_STARTUP=1 the activation never writes the real
    runtime config nor spawns a thread."""
    monkeypatch.setenv("LAYLA_MINIMAL_STARTUP", "1")
    save_config_keys = MagicMock()
    with patch("runtime_safety.save_config_keys", save_config_keys):
        from services.cluster.cluster_pairing import enable_and_activate_sync
        status = enable_and_activate_sync("queen")
    assert status["persisted"] is False
    assert status["activated"] is False
    save_config_keys.assert_not_called()


# ── (c) unpaired / unauthenticated peer is refused ──────────────────────────

def test_is_authorized_peer_requires_secret_and_pairing():
    # No shared secret at all → refuse everyone.
    assert ns.is_authorized_peer("p1", {"peers": {"p1": {}}}) is False
    # Secret but peer not paired → refuse.
    assert ns.is_authorized_peer("stranger", {"cluster_secret_hash": "h", "peers": {"p1": {}}}) is False
    # Secret AND paired → allow.
    assert ns.is_authorized_peer("p1", {"cluster_secret_hash": "h", "peers": {"p1": {}}}) is True


def test_sync_once_refuses_unauthorized_peer(monkeypatch):
    """An online peer that is NOT in our paired set is refused — never synced to."""
    paired_cfg = {
        "cluster_enabled": True,
        "cluster_secret_hash": "secret-hash",
        "peers": {"good-peer": {"name": "good"}},
    }
    monkeypatch.setattr(ns, "_load_cluster_cfg", lambda: paired_cfg)

    rogue = types.SimpleNamespace(
        instance_id="rogue-peer",
        name="rogue",
        status=types.SimpleNamespace(value="online"),
    )
    fake_net = MagicMock()
    fake_net.enabled = True
    fake_net.get_online_peers.return_value = [rogue]

    sync = ns.NodeSync()
    # If sync were (wrongly) attempted, this would blow up the test.
    sync._sync_with_peer = MagicMock(side_effect=AssertionError("must not sync to a rogue peer"))

    with patch("services.cluster.cluster_network.get_cluster_network", return_value=fake_net):
        summary = sync.sync_once()

    assert "rogue-pe" in summary["refused"]  # instance_id[:8]
    assert summary["peers_synced"] == 0
    assert summary["total_pushed"] == 0
    sync._sync_with_peer.assert_not_called()


# ── (d) complete no-op when not paired ──────────────────────────────────────

def test_sync_once_is_noop_when_not_paired(monkeypatch):
    """Until a pair exists, sync_once returns immediately without touching the network."""
    monkeypatch.setattr(ns, "_load_cluster_cfg", lambda: {"cluster_enabled": False, "peers": {}})

    get_net = MagicMock(side_effect=AssertionError("network must not be touched when unpaired"))
    with patch("services.cluster.cluster_network.get_cluster_network", get_net):
        summary = ns.NodeSync().sync_once()

    assert summary["note"] == "not_paired"
    assert summary["peers_synced"] == 0
    get_net.assert_not_called()


def test_sync_paired_reflects_config(monkeypatch):
    # Fresh single-device install: not paired.
    monkeypatch.setattr(ns, "_load_cluster_cfg", lambda: {})
    assert ns.sync_paired() is False
    # Enabled + secret but no peer yet → still not paired.
    monkeypatch.setattr(ns, "_load_cluster_cfg",
                        lambda: {"cluster_enabled": True, "cluster_secret_hash": "h", "peers": {}})
    assert ns.sync_paired() is False
    # Enabled + secret + a paired peer → paired.
    monkeypatch.setattr(ns, "_load_cluster_cfg",
                        lambda: {"cluster_enabled": True, "cluster_secret_hash": "h", "peers": {"p": {}}})
    assert ns.sync_paired() is True
