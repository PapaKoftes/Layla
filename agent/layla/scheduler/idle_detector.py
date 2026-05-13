# -*- coding: utf-8 -*-
"""
idle_detector.py — Detect system idle state for background task scheduling.

Combines CPU usage and optional input detection to determine if the system
is idle enough to run low-priority background tasks (reindex, consolidation,
research queue).

Config keys:
    idle_detection_enabled      bool  (default true)
    idle_cpu_threshold          float (default 0.30)  — CPU usage fraction below which = idle
    idle_timeout_minutes        int   (default 10)    — Minutes of low CPU before idle trigger
    idle_active_cpu_threshold   float (default 0.60)  — CPU above this = definitely active

Usage:
    from layla.scheduler.idle_detector import IdleDetector
    detector = IdleDetector(cfg)
    if detector.is_idle():
        run_low_priority_tasks()
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass

logger = logging.getLogger("layla")


@dataclass
class IdleState:
    """Current idle detection state snapshot."""
    is_idle: bool
    cpu_percent: float
    idle_duration_seconds: float
    last_active_at: float
    reason: str


class IdleDetector:
    """
    Stateful idle detector.

    Tracks CPU usage over time and declares idle when CPU stays below
    threshold for idle_timeout_minutes.
    """

    def __init__(self, cfg: dict | None = None):
        self._cfg = cfg or {}
        self._enabled = bool(self._cfg.get("idle_detection_enabled", True))
        self._cpu_threshold = float(self._cfg.get("idle_cpu_threshold", 0.30))
        self._active_threshold = float(self._cfg.get("idle_active_cpu_threshold", 0.60))
        self._timeout_seconds = int(self._cfg.get("idle_timeout_minutes", 10)) * 60
        self._last_active_at = time.time()
        self._idle_since: float | None = None

    def _get_cpu_percent(self) -> float:
        """Get current CPU usage as 0.0–1.0 fraction. Returns 0.5 if psutil unavailable."""
        try:
            import psutil
            return psutil.cpu_percent(interval=0.5) / 100.0
        except ImportError:
            return 0.5  # Assume moderate usage if can't measure
        except Exception as exc:
            logger.debug("idle_detector: cpu_percent failed: %s", exc)
            return 0.5

    def update(self) -> IdleState:
        """
        Sample CPU and update idle state.

        Call periodically (e.g., every 60 seconds from scheduler).
        """
        if not self._enabled:
            return IdleState(
                is_idle=False, cpu_percent=0.0, idle_duration_seconds=0.0,
                last_active_at=self._last_active_at, reason="idle_detection_disabled",
            )

        cpu = self._get_cpu_percent()
        now = time.time()

        if cpu >= self._active_threshold:
            # Definitely active
            self._last_active_at = now
            self._idle_since = None
            return IdleState(
                is_idle=False, cpu_percent=cpu, idle_duration_seconds=0.0,
                last_active_at=now, reason=f"cpu_active ({cpu:.0%})",
            )

        if cpu < self._cpu_threshold:
            # Low CPU — start or continue idle timer
            if self._idle_since is None:
                self._idle_since = now
            idle_dur = now - self._idle_since
            is_idle = idle_dur >= self._timeout_seconds
            return IdleState(
                is_idle=is_idle, cpu_percent=cpu, idle_duration_seconds=idle_dur,
                last_active_at=self._last_active_at,
                reason=f"cpu_low ({cpu:.0%}) for {idle_dur:.0f}s" + (" → IDLE" if is_idle else ""),
            )

        # Between thresholds — ambiguous, don't reset idle timer but don't declare idle
        idle_dur = (now - self._idle_since) if self._idle_since else 0.0
        return IdleState(
            is_idle=False, cpu_percent=cpu, idle_duration_seconds=idle_dur,
            last_active_at=self._last_active_at,
            reason=f"cpu_moderate ({cpu:.0%})",
        )

    def is_idle(self) -> bool:
        """Quick check: is the system currently idle?"""
        return self.update().is_idle

    def mark_active(self) -> None:
        """Manually mark system as active (e.g., user input received)."""
        self._last_active_at = time.time()
        self._idle_since = None

    def get_state(self) -> IdleState:
        """Get current state without updating."""
        cpu = self._get_cpu_percent()
        now = time.time()
        idle_dur = (now - self._idle_since) if self._idle_since else 0.0
        is_idle = self._idle_since is not None and idle_dur >= self._timeout_seconds
        return IdleState(
            is_idle=is_idle, cpu_percent=cpu, idle_duration_seconds=idle_dur,
            last_active_at=self._last_active_at,
            reason="snapshot",
        )


# Module-level singleton
_detector: IdleDetector | None = None


def get_idle_detector(cfg: dict | None = None) -> IdleDetector:
    """Get or create the singleton IdleDetector."""
    global _detector
    if _detector is None:
        _detector = IdleDetector(cfg)
    return _detector


def check_idle(cfg: dict | None = None) -> bool:
    """Quick module-level idle check."""
    return get_idle_detector(cfg).is_idle()


def mark_user_active() -> None:
    """Call when user sends a message or interacts."""
    if _detector is not None:
        _detector.mark_active()
