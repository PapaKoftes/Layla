# -*- coding: utf-8 -*-
"""
resource_governor.py — Dynamic resource management with OS-level input detection.

Three operating modes based on actual user keyboard/mouse activity:
  WHISPER  — User is active.  Minimal CPU footprint, unload heavy model.
  BREATHE  — User lightly active (1-10min idle).  Moderate background work.
  SPRINT   — User away 10+ minutes.  Full compute utilisation.

Uses Windows GetLastInputInfo via ctypes for real input detection,
falling back to CPU-only heuristics on non-Windows or missing APIs.

Config keys (all in runtime_config.json / runtime_safety defaults):
    resource_governor_enabled    bool   (default True)
    whisper_cpu_cap              float  (default 0.05)  — max CPU fraction in WHISPER
    breathe_cpu_cap              float  (default 0.25)
    sprint_cpu_cap               float  (default 0.80)
    whisper_timeout_seconds      int    (default 60)    — idle seconds before BREATHE
    sprint_timeout_seconds       int    (default 600)   — idle seconds before SPRINT
    governor_tick_seconds        int    (default 15)     — how often to re-evaluate

Usage:
    from services.resource_governor import get_governor, ResourceMode
    gov = get_governor(cfg)
    gov.update()
    if gov.mode == ResourceMode.SPRINT:
        run_heavy_background_tasks()
"""
from __future__ import annotations

import enum
import logging
import platform
import threading
import time
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger("layla.governor")


# ---------------------------------------------------------------------------
# Resource modes
# ---------------------------------------------------------------------------

class ResourceMode(enum.Enum):
    """System operating modes ordered by resource aggressiveness."""
    WHISPER = "whisper"    # User active — stay invisible
    BREATHE = "breathe"    # User lightly idle — moderate work
    SPRINT = "sprint"      # User away — full power


@dataclass
class GovernorState:
    """Snapshot of governor state for observability."""
    mode: ResourceMode
    last_input_seconds: float
    cpu_percent: float
    gpu_used_mb: int
    gpu_total_mb: int
    tick_count: int
    reason: str
    timestamp: float = field(default_factory=time.time)


# ---------------------------------------------------------------------------
# Windows input detection via ctypes
# ---------------------------------------------------------------------------

_HAS_WIN_INPUT = False

if platform.system() == "Windows":
    try:
        import ctypes
        import ctypes.wintypes

        class _LASTINPUTINFO(ctypes.Structure):
            _fields_ = [
                ("cbSize", ctypes.c_uint),
                ("dwTime", ctypes.c_uint),
            ]

        _lii = _LASTINPUTINFO()
        _lii.cbSize = ctypes.sizeof(_LASTINPUTINFO)
        _HAS_WIN_INPUT = True
    except Exception:
        pass


def _get_last_input_seconds_win() -> float:
    """Return seconds since last keyboard/mouse input (Windows only)."""
    try:
        ctypes.windll.user32.GetLastInputInfo(ctypes.byref(_lii))  # type: ignore[name-defined]
        tick_count = ctypes.windll.kernel32.GetTickCount()  # type: ignore[name-defined]
        elapsed_ms = tick_count - _lii.dwTime  # type: ignore[name-defined]
        # Handle tick count rollover (every ~49 days)
        if elapsed_ms < 0:
            elapsed_ms += 0xFFFFFFFF
        return elapsed_ms / 1000.0
    except Exception:
        return -1.0  # Signal that detection failed


def _get_last_input_seconds_fallback() -> float:
    """Fallback: return -1 to signal no input detection available."""
    return -1.0


def get_last_input_seconds() -> float:
    """
    Get seconds since last user keyboard/mouse input.

    Returns -1.0 if input detection is unavailable (non-Windows or API failure).
    """
    if _HAS_WIN_INPUT:
        return _get_last_input_seconds_win()
    return _get_last_input_seconds_fallback()


# ---------------------------------------------------------------------------
# Resource Governor
# ---------------------------------------------------------------------------

class ResourceGovernor:
    """
    Dynamically adjusts Layla's resource consumption based on user activity.

    Composes with the existing IdleDetector (CPU-based) but adds OS-level
    input detection for much more responsive mode switching.
    """

    def __init__(self, cfg: dict | None = None):
        self._cfg = cfg or {}
        self._enabled = bool(self._cfg.get("resource_governor_enabled", True))

        # Thresholds
        self._whisper_cpu_cap = float(self._cfg.get("whisper_cpu_cap", 0.05))
        self._breathe_cpu_cap = float(self._cfg.get("breathe_cpu_cap", 0.25))
        self._sprint_cpu_cap = float(self._cfg.get("sprint_cpu_cap", 0.80))
        self._whisper_timeout = int(self._cfg.get("whisper_timeout_seconds", 60))
        self._sprint_timeout = int(self._cfg.get("sprint_timeout_seconds", 600))
        self._tick_interval = int(self._cfg.get("governor_tick_seconds", 15))

        # State
        self._mode = ResourceMode.WHISPER
        self._lock = threading.Lock()
        self._tick_count = 0
        self._last_mode_change = time.time()
        self._last_state: GovernorState | None = None

        # Callbacks — services register to be notified on mode change
        self._on_mode_change: list[Any] = []

        # Compose with existing idle detector (optional)
        self._idle_detector = None
        try:
            from layla.scheduler.idle_detector import get_idle_detector
            self._idle_detector = get_idle_detector(cfg)
        except Exception:
            pass

    @property
    def mode(self) -> ResourceMode:
        """Current operating mode (thread-safe read)."""
        with self._lock:
            return self._mode

    @property
    def state(self) -> GovernorState | None:
        """Last computed state snapshot."""
        with self._lock:
            return self._last_state

    @property
    def enabled(self) -> bool:
        return self._enabled

    def on_mode_change(self, callback) -> None:
        """Register a callback(old_mode, new_mode) for mode transitions."""
        self._on_mode_change.append(callback)

    def update(self) -> GovernorState:
        """
        Re-evaluate the operating mode. Call every tick_interval seconds.

        Decision logic:
          1. If user input within whisper_timeout → WHISPER
          2. If user input within sprint_timeout → BREATHE
          3. If user idle beyond sprint_timeout → SPRINT
          4. If input detection unavailable → fall back to CPU-only heuristics
        """
        if not self._enabled:
            state = GovernorState(
                mode=ResourceMode.WHISPER,
                last_input_seconds=0.0,
                cpu_percent=0.0,
                gpu_used_mb=0,
                gpu_total_mb=0,
                tick_count=self._tick_count,
                reason="governor_disabled",
            )
            with self._lock:
                self._last_state = state
            return state

        self._tick_count += 1
        input_secs = get_last_input_seconds()
        cpu_pct = self._get_cpu_percent()
        gpu_used, gpu_total = self._get_gpu_usage()

        # Determine mode
        if input_secs >= 0:
            # Input detection available — use it as primary signal
            new_mode = self._classify_by_input(input_secs, cpu_pct)
            reason = f"input_idle={input_secs:.0f}s cpu={cpu_pct:.0%}"
        else:
            # Fallback: CPU-only heuristics (existing idle_detector behaviour)
            new_mode = self._classify_by_cpu(cpu_pct)
            reason = f"cpu_only={cpu_pct:.0%} (no input detection)"

        state = GovernorState(
            mode=new_mode,
            last_input_seconds=max(input_secs, 0.0),
            cpu_percent=cpu_pct,
            gpu_used_mb=gpu_used,
            gpu_total_mb=gpu_total,
            tick_count=self._tick_count,
            reason=reason,
        )

        # Apply mode change
        old_mode = self._mode
        with self._lock:
            self._mode = new_mode
            self._last_state = state
            if new_mode != old_mode:
                self._last_mode_change = time.time()

        if new_mode != old_mode:
            logger.info(
                "governor: mode %s → %s (%s)",
                old_mode.value, new_mode.value, reason,
            )
            for cb in self._on_mode_change:
                try:
                    cb(old_mode, new_mode)
                except Exception as exc:
                    logger.warning("governor: mode_change callback failed: %s", exc)

        return state

    def _classify_by_input(self, input_secs: float, cpu_pct: float) -> ResourceMode:
        """Classify mode using user input idle time (primary method)."""
        if input_secs < self._whisper_timeout:
            return ResourceMode.WHISPER
        if input_secs < self._sprint_timeout:
            return ResourceMode.BREATHE
        return ResourceMode.SPRINT

    def _classify_by_cpu(self, cpu_pct: float) -> ResourceMode:
        """Fallback: classify mode using CPU usage only."""
        if cpu_pct >= 0.50:
            return ResourceMode.WHISPER
        if cpu_pct >= 0.20:
            return ResourceMode.BREATHE
        # CPU is low — check if idle detector agrees
        if self._idle_detector and self._idle_detector.is_idle():
            return ResourceMode.SPRINT
        return ResourceMode.BREATHE

    def _get_cpu_percent(self) -> float:
        """Get CPU usage as 0.0-1.0 fraction."""
        try:
            import psutil
            return psutil.cpu_percent(interval=0.3) / 100.0
        except Exception:
            return 0.5

    def _get_gpu_usage(self) -> tuple[int, int]:
        """Get GPU memory usage (used_mb, total_mb). Returns (0, 0) if unavailable."""
        try:
            import subprocess
            r = subprocess.run(
                ["nvidia-smi", "--query-gpu=memory.used,memory.total",
                 "--format=csv,noheader,nounits"],
                capture_output=True, text=True, timeout=3,
                encoding="utf-8", errors="replace",
            )
            if r.returncode == 0 and r.stdout.strip():
                parts = r.stdout.strip().split("\n")[0].split(",")
                if len(parts) >= 2:
                    return int(parts[0].strip()), int(parts[1].strip())
        except Exception:
            pass
        return 0, 0

    # ------------------------------------------------------------------
    # Resource limit helpers (used by scheduler, worker pool, etc.)
    # ------------------------------------------------------------------

    def get_cpu_cap(self) -> float:
        """Max CPU fraction allowed in current mode."""
        caps = {
            ResourceMode.WHISPER: self._whisper_cpu_cap,
            ResourceMode.BREATHE: self._breathe_cpu_cap,
            ResourceMode.SPRINT: self._sprint_cpu_cap,
        }
        return caps.get(self.mode, self._breathe_cpu_cap)

    def get_max_workers(self) -> int:
        """Max concurrent background worker threads for current mode."""
        workers = {
            ResourceMode.WHISPER: 1,
            ResourceMode.BREATHE: 2,
            ResourceMode.SPRINT: 4,
        }
        return workers.get(self.mode, 2)

    def should_run_background(self, priority: int = 2) -> bool:
        """
        Whether a background task at the given priority should run now.

        priority: 0=critical (always), 1=normal, 2=low-priority
        """
        mode = self.mode
        if priority == 0:
            return True  # Critical tasks always run
        if mode == ResourceMode.WHISPER:
            return False  # No background work while user is active
        if mode == ResourceMode.BREATHE:
            return priority <= 1  # Only normal+ priority in BREATHE
        return True  # SPRINT: run everything

    def should_load_model(self) -> bool:
        """Whether the heavy model should be loaded."""
        return self.mode != ResourceMode.WHISPER

    def get_gpu_layers(self) -> int:
        """
        Recommended n_gpu_layers for current mode.
        Returns -1 for full offload (SPRINT), 0 for CPU-only (WHISPER).
        """
        if self.mode == ResourceMode.WHISPER:
            return 0   # CPU-only — free GPU for user apps
        if self.mode == ResourceMode.BREATHE:
            return -1   # Use GPU but conservatively
        return -1       # SPRINT: full GPU offload

    def get_batch_size(self) -> int:
        """Recommended n_batch for current mode."""
        batches = {
            ResourceMode.WHISPER: 128,
            ResourceMode.BREATHE: 256,
            ResourceMode.SPRINT: 512,
        }
        return batches.get(self.mode, 256)

    def get_inference_threads(self, physical_cores: int) -> int:
        """Recommended llama n_threads for the current mode.

        Leaves CPU headroom for the user when they are active (WHISPER) so a running
        generation can't choke a low-end laptop; uses all cores when idle (SPRINT).
        """
        cores = max(1, int(physical_cores or 1))
        if self.mode == ResourceMode.WHISPER:
            return max(1, cores // 2)     # user active: leave half the cores free
        if self.mode == ResourceMode.BREATHE:
            return max(1, cores - 1)      # lightly idle: most cores
        return cores                      # SPRINT: all cores

    def mark_user_active(self) -> None:
        """
        Manually mark user as active (e.g., incoming chat message).
        Immediately drops to WHISPER if not already.
        """
        if self._idle_detector:
            self._idle_detector.mark_active()
        # Force immediate mode check on next tick
        old = self._mode
        with self._lock:
            if self._mode != ResourceMode.WHISPER:
                self._mode = ResourceMode.WHISPER
                logger.info("governor: forced WHISPER (user_active)")
        # Fire callbacks on the forced transition so priority/throttle apply immediately.
        if old != ResourceMode.WHISPER:
            for cb in self._on_mode_change:
                try:
                    cb(old, ResourceMode.WHISPER)
                except Exception as exc:
                    logger.warning("governor: mode_change callback failed: %s", exc)

    def to_dict(self) -> dict[str, Any]:
        """Serialise current state for API responses."""
        state = self.state
        return {
            "mode": self.mode.value,
            "enabled": self._enabled,
            "last_input_seconds": state.last_input_seconds if state else 0,
            "cpu_percent": round(state.cpu_percent * 100, 1) if state else 0,
            "gpu_used_mb": state.gpu_used_mb if state else 0,
            "gpu_total_mb": state.gpu_total_mb if state else 0,
            "tick_count": state.tick_count if state else 0,
            "cpu_cap_percent": round(self.get_cpu_cap() * 100, 1),
            "max_workers": self.get_max_workers(),
            "model_loaded": self.should_load_model(),
            "gpu_layers": self.get_gpu_layers(),
        }


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------

_governor: ResourceGovernor | None = None
_governor_lock = threading.Lock()


def _apply_process_priority(mode: ResourceMode) -> None:
    """Lower OS process priority when the user is active so Layla never chokes the
    foreground; restore normal when idle. Best-effort, cross-platform (Windows/POSIX)."""
    try:
        import psutil
        proc = psutil.Process()
        if mode == ResourceMode.WHISPER:
            proc.nice(getattr(psutil, "BELOW_NORMAL_PRIORITY_CLASS", 10))
        else:
            proc.nice(getattr(psutil, "NORMAL_PRIORITY_CLASS", 0))
    except Exception:
        pass


def get_governor(cfg: dict | None = None) -> ResourceGovernor:
    """Get or create the singleton ResourceGovernor."""
    global _governor
    with _governor_lock:
        if _governor is None:
            _governor = ResourceGovernor(cfg)
            if _governor.enabled:
                _governor.on_mode_change(lambda old, new: _apply_process_priority(new))
        return _governor


def governor_tick() -> GovernorState:
    """Called by scheduler every tick_interval seconds."""
    gov = get_governor()
    return gov.update()


def get_mode() -> ResourceMode:
    """Quick module-level mode check."""
    return get_governor().mode


def is_sprint() -> bool:
    """Quick check: are we in SPRINT mode?"""
    return get_mode() == ResourceMode.SPRINT


def should_run_background(priority: int = 2) -> bool:
    """Quick check: should a background task at this priority run?"""
    return get_governor().should_run_background(priority)
