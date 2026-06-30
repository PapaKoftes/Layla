"""Task Dispatcher — decides WHERE a task runs based on governor mode + drone availability.

The dispatcher is the brain of the distributed task system.  It decides
whether to run a WorkUnit locally (QUEEN) or offload it to a DRONE node,
based on:

1. Queen's current ResourceMode (WHISPER/BREATHE/SPRINT)
2. Drone availability and current load
3. Task priority (chat responses always local)
4. Task type (inference needs model; embedding is lightweight)
5. Data locality (avoid sending large payloads over network)

Phase 3A of the distributed infrastructure plan.
"""
from __future__ import annotations

import logging
import threading
import time
from typing import Any, Optional

logger = logging.getLogger("layla")


class TaskDispatcher:
    """Decides where tasks run: locally (QUEEN) or on a DRONE.

    Integrates with:
    - ``services.resource_governor`` for current mode
    - ``services.cluster_network`` for peer state
    - ``services.work_unit`` for task queue
    """

    def __init__(self, cfg: dict[str, Any] | None = None):
        self._cfg = cfg or {}
        self._queen_id = self._get_queen_id()
        self._dispatch_lock = threading.Lock()

        # Stats
        self._local_dispatches = 0
        self._remote_dispatches = 0
        self._queued_for_later = 0

    # ── Main dispatch logic ──────────────────────────────────────────

    def dispatch(self, task_dict: dict[str, Any]) -> str:
        """Decide where a task should run.

        Returns the node instance_id to execute on, or "queued" if the
        task should be deferred.

        Parameters
        ----------
        task_dict : dict
            WorkUnit.to_dict() representation.

        Returns
        -------
        str
            instance_id of the target node, or "queued".
        """
        from services.cluster.work_unit import TaskType, TaskPriority

        task_type = task_dict.get("type", "inference")
        priority = task_dict.get("priority", TaskPriority.NORMAL)

        # Rule 1: Interactive chat ALWAYS runs on QUEEN
        if task_type == TaskType.INFERENCE.value and priority == TaskPriority.CRITICAL:
            self._local_dispatches += 1
            return self._queen_id

        # Get governor mode
        mode = self._get_governor_mode()

        # Rule 2: In WHISPER mode, offload everything possible to drones
        if mode == "whisper":
            drone = self._find_available_drone(task_type)
            if drone:
                self._remote_dispatches += 1
                return drone
            # No drone available → queue for later unless critical
            if priority == TaskPriority.CRITICAL:
                self._local_dispatches += 1
                return self._queen_id
            self._queued_for_later += 1
            return "queued"

        # Rule 3: In SPRINT mode, prefer QUEEN (fastest hardware)
        if mode == "sprint":
            queen_load = self._get_queen_load()
            if queen_load < 0.7:
                self._local_dispatches += 1
                return self._queen_id
            # Queen busy → overflow to drones
            drone = self._find_available_drone(task_type)
            if drone:
                self._remote_dispatches += 1
                return drone
            self._local_dispatches += 1
            return self._queen_id

        # Rule 4: BREATHE mode — split work by type
        if mode == "breathe":
            # Lightweight / IO-bound tasks → offload to drones
            if task_type in (
                TaskType.EMBEDDING.value,
                TaskType.INGESTION.value,
                TaskType.BACKUP.value,
            ):
                drone = self._find_available_drone(task_type)
                if drone:
                    self._remote_dispatches += 1
                    return drone
            # Inference, study, consolidation → keep local
            self._local_dispatches += 1
            return self._queen_id

        # Fallback: run locally
        self._local_dispatches += 1
        return self._queen_id

    def dispatch_and_submit(self, task_dict: dict[str, Any]) -> dict[str, Any]:
        """Dispatch a task and submit it to the appropriate queue.

        If dispatched remotely, submits to the drone via cluster network.
        If local, submits to the local task queue.
        If queued, submits to the local queue with 'pending' status.

        Returns a result dict with task_id and target_node.
        """
        from services.cluster.work_unit import WorkUnit, get_task_queue

        target = self.dispatch(task_dict)

        unit = WorkUnit.from_dict(task_dict)

        if target == "queued":
            # Store locally for later processing
            queue = get_task_queue()
            task_id = queue.submit(unit)
            return {
                "task_id": task_id,
                "target_node": "queued",
                "status": "pending",
            }

        if target == self._queen_id:
            # Run locally
            queue = get_task_queue()
            unit.assigned_to = self._queen_id
            task_id = queue.submit(unit)
            return {
                "task_id": task_id,
                "target_node": self._queen_id,
                "status": "pending",
            }

        # Remote drone
        try:
            from services.cluster.cluster_network import get_cluster_network
            net = get_cluster_network()
            peer = net.get_peer(target)
            if peer:
                resp = net.submit_task(peer, task_dict)
                if resp and resp.get("ok"):
                    return {
                        "task_id": resp.get("task_id", unit.id),
                        "target_node": target,
                        "status": "submitted",
                    }
        except Exception as e:
            logger.warning("Remote dispatch to %s failed, falling back to local: %s", target[:8], e)

        # Fallback: run locally
        queue = get_task_queue()
        unit.assigned_to = self._queen_id
        task_id = queue.submit(unit)
        return {
            "task_id": task_id,
            "target_node": self._queen_id,
            "status": "pending",
            "note": "remote_fallback",
        }

    # ── Internal helpers ─────────────────────────────────────────────

    def _get_governor_mode(self) -> str:
        """Get the current resource governor mode."""
        try:
            from services.infrastructure.resource_governor import get_mode
            return get_mode().value
        except Exception:
            return "whisper"

    def _get_queen_load(self) -> float:
        """Get current CPU load as 0-1 fraction."""
        try:
            import psutil
            return psutil.cpu_percent(interval=0) / 100.0
        except Exception:
            return 0.5

    def _get_queen_id(self) -> str:
        """Get this node's instance ID."""
        try:
            from services.cluster.mdns_discovery import get_instance_id
            return get_instance_id()
        except Exception:
            return "local"

    def _find_available_drone(self, task_type: str) -> str | None:
        """Find a connected drone with capacity for this task.

        Returns the instance_id of the best drone, or None.
        """
        try:
            from services.cluster.cluster_network import get_cluster_network
            net = get_cluster_network()
            drones = net.get_online_drones()

            if not drones:
                return None

            # Filter by capability
            capable = [d for d in drones if d.has_capability(task_type)]
            if not capable:
                return None

            # Filter by capacity (not at max tasks)
            available = [
                d for d in capable
                if d.current_tasks < d.max_concurrent_tasks
            ]
            if not available:
                return None

            # Prefer drone with lowest current load
            best = min(available, key=lambda d: d.current_load)
            return best.instance_id

        except Exception as e:
            logger.debug("Drone lookup failed: %s", e)
            return None

    # ── Stats ────────────────────────────────────────────────────────

    def get_stats(self) -> dict[str, Any]:
        """Return dispatch statistics."""
        return {
            "local_dispatches": self._local_dispatches,
            "remote_dispatches": self._remote_dispatches,
            "queued_for_later": self._queued_for_later,
            "queen_id": self._queen_id,
        }


# ── Module-level singleton ───────────────────────────────────────────────

_dispatcher: TaskDispatcher | None = None


def get_task_dispatcher(cfg: dict | None = None) -> TaskDispatcher:
    """Get or create the singleton TaskDispatcher."""
    global _dispatcher
    if _dispatcher is None:
        _dispatcher = TaskDispatcher(cfg)
    return _dispatcher


def dispatch_task(task_dict: dict[str, Any]) -> dict[str, Any]:
    """Convenience: dispatch and submit a task."""
    return get_task_dispatcher().dispatch_and_submit(task_dict)
