"""Tests for services.resource_governor — WHISPER / BREATHE / SPRINT modes."""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from services.infrastructure.resource_governor import (
    GovernorState,
    ResourceGovernor,
    ResourceMode,
    get_last_input_seconds,
)


@pytest.fixture
def cfg():
    return {
        "resource_governor_enabled": True,
        "whisper_cpu_cap": 0.05,
        "breathe_cpu_cap": 0.25,
        "sprint_cpu_cap": 0.80,
        "whisper_timeout_seconds": 60,
        "sprint_timeout_seconds": 600,
        "governor_tick_seconds": 15,
    }


@pytest.fixture
def governor(cfg):
    return ResourceGovernor(cfg)


class TestResourceModes:
    def test_starts_in_whisper(self, governor):
        assert governor.mode == ResourceMode.WHISPER

    def test_whisper_when_user_active(self, governor):
        """User input within 60s → WHISPER."""
        with patch("services.infrastructure.resource_governor.get_last_input_seconds", return_value=10.0):
            with patch.object(governor, "_get_cpu_percent", return_value=0.3):
                state = governor.update()
                assert state.mode == ResourceMode.WHISPER

    def test_breathe_when_lightly_idle(self, governor):
        """User idle 61-599s → BREATHE."""
        with patch("services.infrastructure.resource_governor.get_last_input_seconds", return_value=120.0):
            with patch.object(governor, "_get_cpu_percent", return_value=0.1):
                state = governor.update()
                assert state.mode == ResourceMode.BREATHE

    def test_sprint_when_fully_idle(self, governor):
        """User idle 600+s → SPRINT."""
        with patch("services.infrastructure.resource_governor.get_last_input_seconds", return_value=700.0):
            with patch.object(governor, "_get_cpu_percent", return_value=0.05):
                state = governor.update()
                assert state.mode == ResourceMode.SPRINT

    def test_cpu_fallback_when_no_input_detection(self, governor):
        """If get_last_input_seconds returns -1, use CPU heuristics."""
        with patch("services.infrastructure.resource_governor.get_last_input_seconds", return_value=-1.0):
            with patch.object(governor, "_get_cpu_percent", return_value=0.8):
                state = governor.update()
                assert state.mode == ResourceMode.WHISPER  # High CPU → WHISPER

    def test_cpu_fallback_low_cpu_breathe(self, governor):
        """Low CPU without input detection → BREATHE (not SPRINT without idle detector)."""
        with patch("services.infrastructure.resource_governor.get_last_input_seconds", return_value=-1.0):
            with patch.object(governor, "_get_cpu_percent", return_value=0.15):
                governor._idle_detector = None  # No idle detector
                state = governor.update()
                assert state.mode == ResourceMode.BREATHE


class TestResourceLimits:
    def test_cpu_cap_whisper(self, governor):
        governor._mode = ResourceMode.WHISPER
        assert governor.get_cpu_cap() == 0.05

    def test_cpu_cap_breathe(self, governor):
        governor._mode = ResourceMode.BREATHE
        assert governor.get_cpu_cap() == 0.25

    def test_cpu_cap_sprint(self, governor):
        governor._mode = ResourceMode.SPRINT
        assert governor.get_cpu_cap() == 0.80

    def test_max_workers_whisper(self, governor):
        governor._mode = ResourceMode.WHISPER
        assert governor.get_max_workers() == 1

    def test_max_workers_sprint(self, governor):
        governor._mode = ResourceMode.SPRINT
        assert governor.get_max_workers() == 4

    def test_gpu_layers_whisper(self, governor):
        governor._mode = ResourceMode.WHISPER
        assert governor.get_gpu_layers() == 0  # CPU only

    def test_gpu_layers_sprint(self, governor):
        governor._mode = ResourceMode.SPRINT
        assert governor.get_gpu_layers() == -1  # Full offload


class TestBackgroundScheduling:
    def test_critical_always_runs(self, governor):
        governor._mode = ResourceMode.WHISPER
        assert governor.should_run_background(priority=0) is True

    def test_no_background_in_whisper(self, governor):
        governor._mode = ResourceMode.WHISPER
        assert governor.should_run_background(priority=1) is False
        assert governor.should_run_background(priority=2) is False

    def test_normal_runs_in_breathe(self, governor):
        governor._mode = ResourceMode.BREATHE
        assert governor.should_run_background(priority=1) is True
        assert governor.should_run_background(priority=2) is False  # Low-priority blocked

    def test_everything_runs_in_sprint(self, governor):
        governor._mode = ResourceMode.SPRINT
        assert governor.should_run_background(priority=1) is True
        assert governor.should_run_background(priority=2) is True


class TestModeTransitions:
    def test_mode_change_callback(self, governor):
        """Callbacks fire on mode transitions."""
        transitions = []
        governor.on_mode_change(lambda old, new: transitions.append((old, new)))

        with patch("services.infrastructure.resource_governor.get_last_input_seconds", return_value=700.0):
            with patch.object(governor, "_get_cpu_percent", return_value=0.05):
                governor.update()

        assert len(transitions) == 1
        assert transitions[0] == (ResourceMode.WHISPER, ResourceMode.SPRINT)

    def test_no_callback_on_same_mode(self, governor):
        """No callback when mode stays the same."""
        transitions = []
        governor.on_mode_change(lambda old, new: transitions.append((old, new)))

        with patch("services.infrastructure.resource_governor.get_last_input_seconds", return_value=10.0):
            with patch.object(governor, "_get_cpu_percent", return_value=0.3):
                governor.update()
                governor.update()

        assert len(transitions) == 0  # WHISPER → WHISPER, no change

    def test_mark_user_active_forces_whisper(self, governor):
        governor._mode = ResourceMode.SPRINT
        governor.mark_user_active()
        assert governor.mode == ResourceMode.WHISPER


class TestDisabled:
    def test_disabled_governor_stays_whisper(self):
        gov = ResourceGovernor({"resource_governor_enabled": False})
        state = gov.update()
        assert state.mode == ResourceMode.WHISPER
        assert state.reason == "governor_disabled"


class TestSerialization:
    def test_to_dict(self, governor):
        with patch("services.infrastructure.resource_governor.get_last_input_seconds", return_value=10.0):
            with patch.object(governor, "_get_cpu_percent", return_value=0.3):
                governor.update()

        d = governor.to_dict()
        assert d["mode"] == "whisper"
        assert d["enabled"] is True
        assert "cpu_cap_percent" in d
        assert "max_workers" in d
        assert "gpu_layers" in d


class TestInputDetection:
    def test_fallback_returns_negative(self):
        """On non-Windows, get_last_input_seconds returns -1."""
        with patch("services.infrastructure.resource_governor._HAS_WIN_INPUT", False):
            result = get_last_input_seconds()
            assert result == -1.0
