"""Tests for the Castilla low-end resource levers added to ResourceGovernor.

get_inference_threads leaves CPU headroom when the user is active (so a generation
can't choke a low-end laptop) and uses all cores when idle; _apply_process_priority
lowers/raises OS priority by mode. Pure-stdlib (psutil optional); runs anywhere.
"""
import sys
from pathlib import Path

AGENT_DIR = Path(__file__).resolve().parent.parent
if str(AGENT_DIR) not in sys.path:
    sys.path.insert(0, str(AGENT_DIR))

from services.resource_governor import (  # noqa: E402
    ResourceGovernor,
    ResourceMode,
    _apply_process_priority,
)


def _gov(mode):
    g = ResourceGovernor({"resource_governor_enabled": True})
    g._mode = mode
    return g


def test_whisper_leaves_cpu_headroom_for_user():
    # user active -> use at most half the cores so the laptop stays responsive
    assert _gov(ResourceMode.WHISPER).get_inference_threads(4) == 2
    assert _gov(ResourceMode.WHISPER).get_inference_threads(8) == 4


def test_breathe_uses_most_cores():
    assert _gov(ResourceMode.BREATHE).get_inference_threads(4) == 3


def test_sprint_uses_all_cores():
    # deeply idle -> get the most out of the machine
    assert _gov(ResourceMode.SPRINT).get_inference_threads(4) == 4


def test_thread_count_floors_at_one():
    assert _gov(ResourceMode.WHISPER).get_inference_threads(1) == 1
    assert _gov(ResourceMode.SPRINT).get_inference_threads(0) == 1


def test_monotonic_idle_gives_more_threads():
    w = _gov(ResourceMode.WHISPER).get_inference_threads(4)
    b = _gov(ResourceMode.BREATHE).get_inference_threads(4)
    s = _gov(ResourceMode.SPRINT).get_inference_threads(4)
    assert w <= b <= s  # the more idle, the more compute


def test_apply_process_priority_does_not_raise():
    # best-effort; must never crash even if psutil is missing / perms denied
    _apply_process_priority(ResourceMode.WHISPER)
    _apply_process_priority(ResourceMode.SPRINT)  # restore normal


def test_governor_registers_priority_callback_when_enabled():
    import services.resource_governor as rg
    rg._governor = None  # reset singleton
    gov = rg.get_governor({"resource_governor_enabled": True})
    assert gov.enabled is True
    assert len(gov._on_mode_change) >= 1  # priority callback registered
    rg._governor = None


if __name__ == "__main__":
    import pytest
    sys.exit(pytest.main([__file__, "-v"]))
