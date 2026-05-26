"""Tests for services.task_dispatcher — dispatch routing logic."""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from services.task_dispatcher import TaskDispatcher
from services.work_unit import TaskType, TaskPriority
from services.cluster_network import Peer, PeerStatus, NodeRole


@pytest.fixture
def dispatcher():
    d = TaskDispatcher.__new__(TaskDispatcher)
    d._cfg = {}
    d._queen_id = "queen-001"
    d._dispatch_lock = __import__("threading").Lock()
    d._local_dispatches = 0
    d._remote_dispatches = 0
    d._queued_for_later = 0
    return d


class TestDispatchRules:
    def test_critical_inference_always_local(self, dispatcher):
        """Interactive chat (priority=0, type=inference) always runs on QUEEN."""
        task = {"type": "inference", "priority": TaskPriority.CRITICAL}
        target = dispatcher.dispatch(task)
        assert target == "queen-001"

    def test_whisper_offloads_to_drone(self, dispatcher):
        """WHISPER mode offloads non-critical tasks to drones."""
        with patch.object(dispatcher, "_get_governor_mode", return_value="whisper"):
            with patch.object(dispatcher, "_find_available_drone", return_value="drone-001"):
                task = {"type": "embedding", "priority": TaskPriority.NORMAL}
                target = dispatcher.dispatch(task)
                assert target == "drone-001"

    def test_whisper_queues_when_no_drone(self, dispatcher):
        """WHISPER with no drones queues non-critical tasks."""
        with patch.object(dispatcher, "_get_governor_mode", return_value="whisper"):
            with patch.object(dispatcher, "_find_available_drone", return_value=None):
                task = {"type": "embedding", "priority": TaskPriority.NORMAL}
                target = dispatcher.dispatch(task)
                assert target == "queued"

    def test_whisper_critical_runs_local_when_no_drone(self, dispatcher):
        """Even in WHISPER, critical tasks run locally if no drone available."""
        with patch.object(dispatcher, "_get_governor_mode", return_value="whisper"):
            with patch.object(dispatcher, "_find_available_drone", return_value=None):
                task = {"type": "embedding", "priority": TaskPriority.CRITICAL}
                target = dispatcher.dispatch(task)
                assert target == "queen-001"

    def test_sprint_prefers_queen(self, dispatcher):
        """SPRINT mode prefers QUEEN when load is low."""
        with patch.object(dispatcher, "_get_governor_mode", return_value="sprint"):
            with patch.object(dispatcher, "_get_queen_load", return_value=0.3):
                task = {"type": "embedding", "priority": TaskPriority.NORMAL}
                target = dispatcher.dispatch(task)
                assert target == "queen-001"

    def test_sprint_overflows_to_drone(self, dispatcher):
        """SPRINT overflows to drone when queen is busy."""
        with patch.object(dispatcher, "_get_governor_mode", return_value="sprint"):
            with patch.object(dispatcher, "_get_queen_load", return_value=0.85):
                with patch.object(dispatcher, "_find_available_drone", return_value="drone-002"):
                    task = {"type": "ingestion", "priority": TaskPriority.NORMAL}
                    target = dispatcher.dispatch(task)
                    assert target == "drone-002"

    def test_breathe_offloads_embedding(self, dispatcher):
        """BREATHE offloads embedding/ingestion tasks to drones."""
        with patch.object(dispatcher, "_get_governor_mode", return_value="breathe"):
            with patch.object(dispatcher, "_find_available_drone", return_value="drone-003"):
                task = {"type": "embedding", "priority": TaskPriority.NORMAL}
                target = dispatcher.dispatch(task)
                assert target == "drone-003"

    def test_breathe_keeps_inference_local(self, dispatcher):
        """BREATHE keeps inference locally."""
        with patch.object(dispatcher, "_get_governor_mode", return_value="breathe"):
            task = {"type": "inference", "priority": TaskPriority.NORMAL}
            target = dispatcher.dispatch(task)
            assert target == "queen-001"


class TestDroneFinding:
    def test_find_available_drone(self, dispatcher):
        """Finds the drone with lowest load."""
        mock_net = MagicMock()
        mock_net.get_online_drones.return_value = [
            Peer(instance_id="d1", status=PeerStatus.ONLINE, current_load=0.8, current_tasks=1, max_concurrent_tasks=2),
            Peer(instance_id="d2", status=PeerStatus.ONLINE, current_load=0.2, current_tasks=0, max_concurrent_tasks=2),
        ]
        with patch("services.cluster_network.get_cluster_network", return_value=mock_net):
            result = dispatcher._find_available_drone("embedding")
            assert result == "d2"

    def test_find_no_drone_when_all_full(self, dispatcher):
        """Returns None when all drones are at capacity."""
        mock_net = MagicMock()
        mock_net.get_online_drones.return_value = [
            Peer(instance_id="d1", status=PeerStatus.ONLINE, current_tasks=2, max_concurrent_tasks=2),
        ]
        with patch("services.cluster_network.get_cluster_network", return_value=mock_net):
            result = dispatcher._find_available_drone("embedding")
            assert result is None

    def test_find_no_drone_when_none_online(self, dispatcher):
        """Returns None when no drones are online."""
        mock_net = MagicMock()
        mock_net.get_online_drones.return_value = []
        with patch("services.cluster_network.get_cluster_network", return_value=mock_net):
            result = dispatcher._find_available_drone("embedding")
            assert result is None


class TestStats:
    def test_stats_tracking(self, dispatcher):
        """Dispatch counters increment correctly."""
        with patch.object(dispatcher, "_get_governor_mode", return_value="sprint"):
            with patch.object(dispatcher, "_get_queen_load", return_value=0.3):
                dispatcher.dispatch({"type": "inference", "priority": 1})
                dispatcher.dispatch({"type": "embedding", "priority": 1})

        stats = dispatcher.get_stats()
        assert stats["local_dispatches"] == 2
        assert stats["queen_id"] == "queen-001"
