# -*- coding: utf-8 -*-
"""
Tests for Phase 6: Autonomy Engine.

Covers:
  - Idle detector (IdleDetector, IdleState, check_idle, mark_user_active)
  - Long-horizon planner (decompose_to_horizon, DayChunk, LongHorizonPlan,
    checkpoint save/load, advance_chunk, get_next_chunk)
  - Mission board API (pause, resume, cancel, board, horizon endpoints)
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

AGENT_DIR = Path(__file__).resolve().parent.parent
if str(AGENT_DIR) not in sys.path:
    sys.path.insert(0, str(AGENT_DIR))


# ============================================================================
# Tests: Idle Detector
# ============================================================================


class TestIdleState:
    def test_creation(self):
        from layla.scheduler.idle_detector import IdleState
        state = IdleState(
            is_idle=True, cpu_percent=0.15, idle_duration_seconds=600,
            last_active_at=time.time() - 600, reason="cpu_low",
        )
        assert state.is_idle is True
        assert state.cpu_percent == 0.15
        assert state.idle_duration_seconds == 600


class TestIdleDetector:
    def test_disabled_returns_not_idle(self):
        from layla.scheduler.idle_detector import IdleDetector
        d = IdleDetector(cfg={"idle_detection_enabled": False})
        state = d.update()
        assert state.is_idle is False
        assert state.reason == "idle_detection_disabled"

    @patch("layla.scheduler.idle_detector.IdleDetector._get_cpu_percent", return_value=0.10)
    def test_low_cpu_starts_idle_timer(self, mock_cpu):
        from layla.scheduler.idle_detector import IdleDetector
        d = IdleDetector(cfg={"idle_detection_enabled": True, "idle_timeout_minutes": 1})
        state = d.update()
        assert state.is_idle is False  # Not idle yet — timer just started
        assert "cpu_low" in state.reason

    @patch("layla.scheduler.idle_detector.IdleDetector._get_cpu_percent", return_value=0.10)
    def test_idle_after_timeout(self, mock_cpu):
        from layla.scheduler.idle_detector import IdleDetector
        d = IdleDetector(cfg={"idle_detection_enabled": True, "idle_timeout_minutes": 1})
        # Simulate: idle_since was 2 minutes ago
        d._idle_since = time.time() - 120
        state = d.update()
        assert state.is_idle is True

    @patch("layla.scheduler.idle_detector.IdleDetector._get_cpu_percent", return_value=0.80)
    def test_high_cpu_resets_idle(self, mock_cpu):
        from layla.scheduler.idle_detector import IdleDetector
        d = IdleDetector(cfg={"idle_detection_enabled": True})
        d._idle_since = time.time() - 600  # Was idle
        state = d.update()
        assert state.is_idle is False
        assert d._idle_since is None  # Timer reset

    def test_mark_active(self):
        from layla.scheduler.idle_detector import IdleDetector
        d = IdleDetector()
        d._idle_since = time.time() - 600
        d.mark_active()
        assert d._idle_since is None

    @patch("layla.scheduler.idle_detector.IdleDetector._get_cpu_percent", return_value=0.45)
    def test_moderate_cpu_ambiguous(self, mock_cpu):
        from layla.scheduler.idle_detector import IdleDetector
        d = IdleDetector(cfg={"idle_detection_enabled": True})
        state = d.update()
        assert state.is_idle is False
        assert "moderate" in state.reason

    def test_is_idle_shortcut(self):
        from layla.scheduler.idle_detector import IdleDetector
        d = IdleDetector(cfg={"idle_detection_enabled": False})
        assert d.is_idle() is False


class TestModuleLevelIdleFunctions:
    def test_check_idle(self):
        from layla.scheduler.idle_detector import check_idle
        # Should not raise; returns bool
        result = check_idle(cfg={"idle_detection_enabled": False})
        assert result is False

    def test_mark_user_active(self):
        from layla.scheduler.idle_detector import get_idle_detector, mark_user_active
        get_idle_detector()  # Ensure singleton exists
        mark_user_active()  # Should not raise

    def test_get_idle_detector_singleton(self):
        import layla.scheduler.idle_detector as mod
        mod._detector = None  # Reset
        d1 = mod.get_idle_detector({"idle_detection_enabled": True})
        d2 = mod.get_idle_detector()
        assert d1 is d2


# ============================================================================
# Tests: Long-Horizon Planner
# ============================================================================


class TestDayChunk:
    def test_creation(self):
        from services.long_horizon_planner import DayChunk
        chunk = DayChunk(day=1, title="Research", goal="Understand the problem")
        assert chunk.day == 1
        assert chunk.status == "pending"
        assert chunk.depends_on == []

    def test_to_dict(self):
        from services.long_horizon_planner import DayChunk
        chunk = DayChunk(day=2, title="Build", goal="Implement core", depends_on=[1])
        d = chunk.to_dict()
        assert d["day"] == 2
        assert d["depends_on"] == [1]


class TestLongHorizonPlan:
    def test_creation(self):
        from services.long_horizon_planner import DayChunk, LongHorizonPlan
        plan = LongHorizonPlan(
            id="test123", goal="Build feature X",
            chunks=[DayChunk(day=1, title="D1", goal="G1")],
        )
        assert plan.id == "test123"
        assert len(plan.chunks) == 1

    def test_to_dict_round_trip(self):
        from services.long_horizon_planner import DayChunk, LongHorizonPlan
        plan = LongHorizonPlan(
            id="abc", goal="Test goal",
            chunks=[
                DayChunk(day=1, title="Day 1", goal="Start", depends_on=[]),
                DayChunk(day=2, title="Day 2", goal="Continue", depends_on=[1]),
            ],
            total_estimated_hours=8.0,
        )
        d = plan.to_dict()
        restored = LongHorizonPlan.from_dict(d)
        assert restored.id == "abc"
        assert len(restored.chunks) == 2
        assert restored.chunks[1].depends_on == [1]

    def test_from_dict_with_missing_fields(self):
        from services.long_horizon_planner import LongHorizonPlan
        plan = LongHorizonPlan.from_dict({"id": "x", "goal": "y"})
        assert plan.id == "x"
        assert plan.chunks == []


class TestDecomposeToHorizon:
    def test_disabled_returns_single_chunk(self):
        from services.long_horizon_planner import decompose_to_horizon
        plan = decompose_to_horizon("Build a widget", cfg={"long_horizon_enabled": False})
        assert len(plan.chunks) == 1
        assert plan.chunks[0].goal == "Build a widget"

    def test_heuristic_decompose(self):
        from services.long_horizon_planner import decompose_to_horizon
        # With LLM unavailable, should fall back to heuristic.
        # Use a complex enough goal to trigger multi-day splitting.
        plan = decompose_to_horizon(
            "Complete comprehensive refactoring and redesign of the entire authentication system "
            "including database migrations, API endpoint restructuring, frontend component rewrite, "
            "full test coverage, documentation overhaul, security audit, performance optimization, "
            "deployment pipeline updates, and backward compatibility testing across all environments",
            cfg={"long_horizon_enabled": True, "hours_per_day_chunk": 2.0},
        )
        assert len(plan.chunks) >= 2
        assert plan.total_estimated_hours > 0
        # First chunk should be research/planning
        assert "Research" in plan.chunks[0].title or "Planning" in plan.chunks[0].title

    def test_dependency_chain(self):
        from services.long_horizon_planner import decompose_to_horizon
        plan = decompose_to_horizon(
            "Refactor entire codebase architecture",
            cfg={"long_horizon_enabled": True, "max_horizon_days": 5},
        )
        # Later chunks should depend on earlier ones
        for chunk in plan.chunks[1:]:
            assert len(chunk.depends_on) > 0


class TestEstimateComplexity:
    def test_simple_task(self):
        from services.long_horizon_planner import _estimate_complexity
        hours = _estimate_complexity("fix a bug")
        assert hours >= 2.0

    def test_complex_task(self):
        from services.long_horizon_planner import _estimate_complexity
        hours = _estimate_complexity(
            "Complete comprehensive refactoring of the entire authentication system "
            "including database migrations, API endpoints, frontend components, "
            "testing, and full documentation coverage across all modules"
        )
        assert hours > 5.0

    def test_keyword_multipliers(self):
        from services.long_horizon_planner import _estimate_complexity
        h1 = _estimate_complexity("update a function")
        h2 = _estimate_complexity("refactor the complete module")
        assert h2 > h1


class TestCheckpointManagement:
    def test_save_and_load(self, tmp_path):
        from services.long_horizon_planner import (
            DayChunk, LongHorizonPlan, load_checkpoint, save_checkpoint,
        )
        import services.long_horizon_planner as mod
        original_dir = mod._CHECKPOINT_DIR
        mod._CHECKPOINT_DIR = tmp_path / "checkpoints"

        try:
            plan = LongHorizonPlan(
                id="test_cp", goal="Checkpoint test",
                chunks=[DayChunk(day=1, title="Day 1", goal="Test")],
            )
            path = save_checkpoint(plan)
            assert Path(path).is_file()

            loaded = load_checkpoint("test_cp")
            assert loaded is not None
            assert loaded.id == "test_cp"
            assert loaded.goal == "Checkpoint test"
        finally:
            mod._CHECKPOINT_DIR = original_dir

    def test_load_nonexistent(self, tmp_path):
        from services.long_horizon_planner import load_checkpoint
        import services.long_horizon_planner as mod
        original_dir = mod._CHECKPOINT_DIR
        mod._CHECKPOINT_DIR = tmp_path / "checkpoints"

        try:
            assert load_checkpoint("nonexistent") is None
        finally:
            mod._CHECKPOINT_DIR = original_dir

    def test_list_checkpoints(self, tmp_path):
        from services.long_horizon_planner import (
            DayChunk, LongHorizonPlan, list_checkpoints, save_checkpoint,
        )
        import services.long_horizon_planner as mod
        original_dir = mod._CHECKPOINT_DIR
        mod._CHECKPOINT_DIR = tmp_path / "checkpoints"

        try:
            plan = LongHorizonPlan(
                id="list_test", goal="List test",
                chunks=[DayChunk(day=1, title="D1", goal="G1")],
            )
            save_checkpoint(plan)
            cps = list_checkpoints()
            assert len(cps) >= 1
            assert cps[0]["id"] == "list_test"
        finally:
            mod._CHECKPOINT_DIR = original_dir


class TestAdvanceChunk:
    def test_advance_marks_done(self):
        from services.long_horizon_planner import DayChunk, LongHorizonPlan, advance_chunk
        plan = LongHorizonPlan(
            id="adv", goal="test",
            chunks=[
                DayChunk(day=1, title="D1", goal="G1"),
                DayChunk(day=2, title="D2", goal="G2", depends_on=[1]),
            ],
        )
        assert advance_chunk(plan, 1) is True
        assert plan.chunks[0].status == "done"

    def test_advance_nonexistent_day(self):
        from services.long_horizon_planner import DayChunk, LongHorizonPlan, advance_chunk
        plan = LongHorizonPlan(id="x", goal="y", chunks=[DayChunk(day=1, title="D1", goal="G1")])
        assert advance_chunk(plan, 99) is False

    def test_all_done_completes_plan(self):
        from services.long_horizon_planner import DayChunk, LongHorizonPlan, advance_chunk
        plan = LongHorizonPlan(
            id="done", goal="done",
            chunks=[DayChunk(day=1, title="D1", goal="G1")],
        )
        advance_chunk(plan, 1)
        assert plan.status == "completed"

    def test_unblocks_dependents(self):
        from services.long_horizon_planner import DayChunk, LongHorizonPlan, advance_chunk
        plan = LongHorizonPlan(
            id="dep", goal="dep",
            chunks=[
                DayChunk(day=1, title="D1", goal="G1"),
                DayChunk(day=2, title="D2", goal="G2", depends_on=[1], status="blocked"),
            ],
        )
        advance_chunk(plan, 1)
        assert plan.chunks[1].status == "pending"  # Unblocked


class TestGetNextChunk:
    def test_returns_first_pending(self):
        from services.long_horizon_planner import DayChunk, LongHorizonPlan, get_next_chunk
        plan = LongHorizonPlan(
            id="next", goal="next",
            chunks=[
                DayChunk(day=1, title="D1", goal="G1"),
                DayChunk(day=2, title="D2", goal="G2", depends_on=[1]),
            ],
        )
        nxt = get_next_chunk(plan)
        assert nxt is not None
        assert nxt.day == 1

    def test_skips_blocked(self):
        from services.long_horizon_planner import DayChunk, LongHorizonPlan, get_next_chunk
        plan = LongHorizonPlan(
            id="blk", goal="blk",
            chunks=[
                DayChunk(day=1, title="D1", goal="G1", status="done"),
                DayChunk(day=2, title="D2", goal="G2", depends_on=[1]),
            ],
        )
        nxt = get_next_chunk(plan)
        assert nxt is not None
        assert nxt.day == 2

    def test_returns_none_when_all_done(self):
        from services.long_horizon_planner import DayChunk, LongHorizonPlan, get_next_chunk
        plan = LongHorizonPlan(
            id="alldone", goal="done",
            chunks=[DayChunk(day=1, title="D1", goal="G1", status="done")],
        )
        assert get_next_chunk(plan) is None


# ============================================================================
# Tests: Mission Board Router
# ============================================================================


class TestMissionBoardRouter:
    def test_missions_router_importable(self):
        from routers.missions import router
        assert hasattr(router, "routes")

    def test_has_board_endpoint(self):
        from routers.missions import router
        paths = [r.path for r in router.routes if hasattr(r, "path")]
        assert "/missions/board" in paths

    def test_has_horizon_endpoint(self):
        from routers.missions import router
        paths = [r.path for r in router.routes if hasattr(r, "path")]
        assert "/missions/horizon" in paths

    def test_has_pause_endpoint(self):
        from routers.missions import router
        paths = [r.path for r in router.routes if hasattr(r, "path")]
        assert "/mission/{mission_id}/pause" in paths

    def test_has_resume_endpoint(self):
        from routers.missions import router
        paths = [r.path for r in router.routes if hasattr(r, "path")]
        assert "/mission/{mission_id}/resume" in paths

    def test_has_cancel_endpoint(self):
        from routers.missions import router
        paths = [r.path for r in router.routes if hasattr(r, "path")]
        assert "/mission/{mission_id}/cancel" in paths
