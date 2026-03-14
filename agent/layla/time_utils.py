"""
Time utilities for Python 3.11+ compatibility.
datetime.utcnow() is deprecated in 3.12; use timezone-aware datetime.
"""
from datetime import datetime, timezone


def utcnow() -> datetime:
    """Current UTC time (timezone-aware). Replaces deprecated datetime.utcnow()."""
    return datetime.now(timezone.utc)


def utcnow_iso() -> str:
    """Current UTC as ISO string."""
    return utcnow().isoformat()
