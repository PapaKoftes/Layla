"""
Hardware probe for Layla installer.
Delegates to services.hardware_detect (single source of truth).
Kept for backward compatibility with install flow.
"""
from __future__ import annotations

from services.hardware_detect import classify_hardware, detect_hardware


def probe_hardware() -> dict:
    """Detect hardware. Delegates to services.hardware_detect.detect_hardware()."""
    return detect_hardware()


__all__ = ["probe_hardware", "classify_hardware"]
