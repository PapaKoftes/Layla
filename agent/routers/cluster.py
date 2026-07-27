"""
cluster.py — Cluster task dispatch, sync, and status endpoints.

Endpoints:
  POST /cluster/heartbeat           — Peer heartbeat (status update)
  POST /cluster/task/submit          — Submit a WorkUnit to this node
  GET  /cluster/task/{task_id}/status — Poll task status
  POST /cluster/task/{task_id}/cancel — Cancel a running task
  POST /cluster/sync/push            — Push learnings from a peer
  POST /cluster/sync/pull            — Pull learnings since timestamp
  GET  /cluster/status               — Node health + capabilities
  POST /cluster/pair                 — One-time pairing (QUEEN only)
  GET  /cluster/pair/token           — Generate a pairing token (QUEEN only)
  GET  /cluster/peers                — List known peers + status
  GET  /cluster/queue/stats          — Task queue statistics

All endpoints except /cluster/pair require cluster auth
(Authorization: Bearer <cluster_secret>).

Phase 2C of the distributed infrastructure plan.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import logging
import time
import uuid
from datetime import datetime, timezone
from typing import Any, Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

logger = logging.getLogger("layla.cluster")

router = APIRouter(prefix="/cluster", tags=["cluster"])


# ── Request / Response models ────────────────────────────────────────────

class HeartbeatRequest(BaseModel):
    instance_id: str
    name: str = ""
    role: str = "drone"
    timestamp: str = ""
    governor_mode: str = "whisper"
    current_load: float = 0.0
    current_tasks: int = 0


class HeartbeatResponse(BaseModel):
    ok: bool = True
    instance_id: str = ""
    governor_mode: str = "whisper"
    current_load: float = 0.0
    current_tasks: int = 0


class TaskSubmitRequest(BaseModel):
    id: str = ""
    type: str = "inference"
    priority: int = 1
    payload: dict = Field(default_factory=dict)
    timeout_seconds: int = 300
    source_node: str = ""


class TaskStatusResponse(BaseModel):
    id: str
    type: str
    status: str
    priority: int = 1
    assigned_to: Optional[str] = None
    result: Optional[dict] = None
    error: Optional[str] = None
    created_at: str = ""
    started_at: Optional[str] = None
    completed_at: Optional[str] = None


class SyncPushRequest(BaseModel):
    # Legacy flat learnings list (older peers) + the new per-kind records map.
    learnings: list[dict] = Field(default_factory=list)
    records: dict[str, list[dict]] = Field(default_factory=dict)


class SyncPullRequest(BaseModel):
    since: str = "2000-01-01T00:00:00Z"  # ISO timestamp (legacy / fallback)
    since_map: dict[str, str] = Field(default_factory=dict)  # per-kind watermark
    kinds: list[str] = Field(default_factory=list)  # which kinds to return


class PairRequest(BaseModel):
    pairing_token: str
    instance_id: str
    name: str = ""
    address: str = ""
    hardware_tier: str = "cpu"


# ── Auth helper ──────────────────────────────────────────────────────────

def _validate_cluster_auth(request: Request) -> bool:
    """Validate the cluster Bearer token.

    Accepts the cluster secret hash from cluster_config.json
    or the tunnel_token from runtime_safety config.
    Localhost requests are always allowed.
    """
    # Localhost bypass
    client_ip = request.client.host if request.client else "127.0.0.1"
    if client_ip in ("127.0.0.1", "::1", "localhost"):
        return True

    auth_header = request.headers.get("authorization", "")
    if not auth_header.startswith("Bearer "):
        return False
    token = auth_header[7:]

    # Check cluster secret
    try:
        from services.cluster.cluster_network import load_cluster_config
        config = load_cluster_config()
        stored_hash = config.get("cluster_secret_hash", "")
        if stored_hash:
            token_hash = hashlib.sha256(token.encode()).hexdigest()
            if hmac.compare_digest(token_hash, stored_hash):
                return True
    except Exception:
        pass

    # Fallback to tunnel auth
    try:
        from runtime_safety import load_config
        from services.governance.tunnel_auth import validate_token
        cfg = load_config()
        valid, _ = validate_token(token, cfg)
        return valid
    except Exception:
        pass

    return False


def _require_auth(request: Request) -> None:
    """Raise 401 if auth fails."""
    if not _validate_cluster_auth(request):
        raise HTTPException(status_code=401, detail="Unauthorized")


# ── Heartbeat ────────────────────────────────────────────────────────────

@router.post("/heartbeat", response_model=HeartbeatResponse)
async def cluster_heartbeat(body: HeartbeatRequest, request: Request):
    """Receive a heartbeat from a peer node."""
    _require_auth(request)

    try:
        from services.cluster.cluster_network import PeerStatus, get_cluster_network
        net = get_cluster_network()
        peer = net.get_peer(body.instance_id)
        if peer:
            peer.last_heartbeat = time.time()
            peer.status = PeerStatus.ONLINE
            peer.governor_mode = body.governor_mode
            peer.current_load = body.current_load
            peer.current_tasks = body.current_tasks
            if body.name and not peer.name:
                peer.name = body.name
    except Exception as e:
        logger.debug("Heartbeat processing: %s", e)

    # Return our own status
    response = HeartbeatResponse(ok=True)
    try:
        from services.cluster.cluster_network import get_cluster_network
        net = get_cluster_network()
        response.instance_id = net.instance_id
    except Exception:
        pass
    try:
        from services.infrastructure.resource_governor import get_mode
        response.governor_mode = get_mode().value
    except Exception:
        pass
    try:
        import psutil
        response.current_load = psutil.cpu_percent(interval=0) / 100.0
    except Exception:
        pass
    try:
        from services.cluster.work_unit import get_task_queue
        running = get_task_queue().get_running()
        response.current_tasks = len(running)
    except Exception:
        pass

    return response


# ── Task submission ──────────────────────────────────────────────────────

@router.post("/task/submit")
async def cluster_task_submit(body: TaskSubmitRequest, request: Request):
    """Accept a task from a remote node for local execution."""
    _require_auth(request)

    try:
        from services.cluster.work_unit import TaskStatus, TaskType, WorkUnit, get_task_queue

        unit = WorkUnit(
            id=body.id if body.id else uuid.uuid4().hex[:16],
            type=TaskType(body.type),
            priority=body.priority,
            payload=body.payload,
            timeout_seconds=body.timeout_seconds,
            source_node=body.source_node,
            status=TaskStatus.PENDING,
        )
        queue = get_task_queue()
        task_id = queue.submit(unit)

        return {"ok": True, "task_id": task_id, "status": "pending"}
    except Exception as e:
        logger.warning("Task submission failed: %s", e)
        raise HTTPException(status_code=500, detail="internal error")


@router.get("/task/{task_id}/status", response_model=TaskStatusResponse)
async def cluster_task_status(task_id: str, request: Request):
    """Poll the status of a submitted task."""
    _require_auth(request)

    try:
        from services.cluster.work_unit import get_task_queue
        queue = get_task_queue()
        unit = queue.get(task_id)
        if not unit:
            raise HTTPException(status_code=404, detail="Task not found")
        d = unit.to_dict()
        return TaskStatusResponse(**{k: v for k, v in d.items() if k in TaskStatusResponse.model_fields})
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(status_code=500, detail="internal error")


@router.post("/task/{task_id}/cancel")
async def cluster_task_cancel(task_id: str, request: Request):
    """Cancel a pending or running task."""
    _require_auth(request)

    try:
        from services.cluster.work_unit import get_task_queue
        queue = get_task_queue()
        cancelled = queue.cancel(task_id)
        return {"ok": cancelled, "task_id": task_id}
    except Exception:
        raise HTTPException(status_code=500, detail="internal error")


# ── Knowledge sync ───────────────────────────────────────────────────────

@router.post("/sync/push")
async def cluster_sync_push(body: SyncPushRequest, request: Request):
    """Receive knowledge pushed from a paired peer node.

    Accepts the new per-kind ``records`` map (learnings + memories + wiki) and
    the legacy flat ``learnings`` list.  All import runs through the shared
    node_sync dedup path so a two-way sync can never loop or double-import.
    """
    _require_auth(request)

    try:
        from services.cluster.node_sync import SYNC_KINDS, import_records

        # Merge legacy learnings into the records map (records wins if both present).
        by_kind: dict[str, list[dict]] = dict(body.records or {})
        if body.learnings:
            by_kind.setdefault("learning", list(body.learnings))

        total_imported = 0
        total_skipped = 0
        per_kind: dict[str, dict] = {}
        for kind, records in by_kind.items():
            if kind not in SYNC_KINDS:
                continue
            counts = import_records(kind, records, source_label="cluster_sync")
            per_kind[kind] = counts
            total_imported += counts.get("imported", 0)
            total_skipped += counts.get("skipped", 0)
    except Exception as e:
        logger.warning("Sync push failed: %s", e)
        raise HTTPException(status_code=500, detail="internal error")

    logger.info("Sync push: imported %d, skipped %d duplicates", total_imported, total_skipped)
    # Keep top-level imported/skipped for legacy peers; add per-kind detail.
    return {"ok": True, "imported": total_imported, "skipped": total_skipped, "by_kind": per_kind}


@router.post("/sync/pull")
async def cluster_sync_pull(body: SyncPullRequest, request: Request):
    """Return knowledge created since the caller's per-kind watermark.

    Returns both the new per-kind ``records`` map and a legacy flat ``learnings``
    list (so an older peer that only reads ``learnings`` still works).
    """
    _require_auth(request)

    try:
        from services.cluster.node_sync import SYNC_KINDS, export_since

        kinds = [k for k in (body.kinds or ["learning"]) if k in SYNC_KINDS]
        records: dict[str, list[dict]] = {}
        for kind in kinds:
            since = (body.since_map or {}).get(kind, body.since)
            records[kind] = export_since(kind, since)

        # Legacy field: the learning kind as a flat list.
        learnings = records.get("learning")
        if learnings is None:
            learnings = export_since("learning", (body.since_map or {}).get("learning", body.since))

        count = sum(len(v) for v in records.values())
        return {"ok": True, "records": records, "learnings": learnings, "count": count}
    except Exception as e:
        logger.warning("Sync pull failed: %s", e)
        raise HTTPException(status_code=500, detail="internal error")


# ── Cluster status ───────────────────────────────────────────────────────

@router.get("/status")
async def cluster_status(request: Request):
    """Node health + cluster overview."""
    # Status is public for localhost, authed for remote
    client_ip = request.client.host if request.client else "127.0.0.1"
    if client_ip not in ("127.0.0.1", "::1", "localhost"):
        _require_auth(request)

    result: dict[str, Any] = {"ok": True}

    try:
        from services.cluster.cluster_network import get_cluster_status
        result.update(get_cluster_status())
    except Exception:
        # Match the success-path field names (get_cluster_status returns `enabled` + `peer_count`); the
        # old fallback used `cluster_enabled`, so the two paths disagreed and the UI's field read broke
        # depending on which path ran. Keep them identical.
        result["enabled"] = False
        result["peer_count"] = 0

    try:
        from services.infrastructure.resource_governor import get_mode
        result["governor_mode"] = get_mode().value
    except Exception:
        result["governor_mode"] = "unknown"

    try:
        import psutil
        result["cpu_percent"] = psutil.cpu_percent(interval=0)
        mem = psutil.virtual_memory()
        result["memory_used_gb"] = round(mem.used / (1024**3), 1)
        result["memory_total_gb"] = round(mem.total / (1024**3), 1)
    except Exception:
        pass

    try:
        from services.cluster.work_unit import get_task_queue
        result["queue_stats"] = get_task_queue().stats()
    except Exception:
        result["queue_stats"] = {}

    return result


# ── Pairing ──────────────────────────────────────────────────────────────

@router.get("/pair/token")
async def cluster_generate_pairing_token(request: Request):
    """Generate a pairing token for a drone to join (QUEEN only).

    Only accessible from localhost.
    """
    client_ip = request.client.host if request.client else ""
    if client_ip not in ("127.0.0.1", "::1", "localhost"):
        raise HTTPException(status_code=403, detail="Pairing tokens can only be generated locally")

    try:
        from services.cluster.cluster_pairing import get_cluster_pairing
        pairing = get_cluster_pairing()
        pt = pairing.generate_pairing_token()
        return {
            "ok": True,
            "token": pt.token,
            "expires_in_seconds": int(pt.expires_at - pt.created_at),
            "instructions": "Share this token with the drone. It expires in 10 minutes.",
        }
    except Exception:
        raise HTTPException(status_code=500, detail="internal error")


@router.post("/pair")
async def cluster_pair(body: PairRequest, request: Request):
    """Accept a pairing request from a DRONE.

    No auth required (the pairing token IS the auth).
    """
    try:
        from services.cluster.cluster_pairing import get_cluster_pairing
        pairing = get_cluster_pairing()

        # Validate the token
        valid, reason = pairing.validate_pairing_token(body.pairing_token)
        if not valid:
            raise HTTPException(
                status_code=401,
                detail=f"Pairing failed: {reason}",
            )

        # Accept the drone
        result = pairing.accept_drone(
            drone_instance_id=body.instance_id,
            drone_name=body.name,
            drone_address=body.address,
            drone_hardware_tier=body.hardware_tier,
        )
        return result
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Pairing failed: %s", e)
        raise HTTPException(status_code=500, detail="internal error")


# ── Peers listing ────────────────────────────────────────────────────────

@router.get("/peers")
async def cluster_peers(request: Request):
    """List all known cluster peers and their status."""
    _require_auth(request)

    try:
        from services.cluster.cluster_network import get_cluster_network
        net = get_cluster_network()
        status = net.get_status()
        return {"ok": True, "peers": status.get("peers", [])}
    except Exception as e:
        return {"ok": False, "peers": [], "error": str(e)}


# ── Queue stats ──────────────────────────────────────────────────────────

@router.get("/queue/stats")
async def cluster_queue_stats(request: Request):
    """Task queue statistics."""
    _require_auth(request)

    try:
        from services.cluster.work_unit import get_task_queue
        queue = get_task_queue()
        return {
            "ok": True,
            "stats": queue.stats(),
            "pending": [u.to_dict() for u in queue.get_pending(10)],
            "running": [u.to_dict() for u in queue.get_running()],
        }
    except Exception as e:
        return {"ok": False, "error": str(e)}
