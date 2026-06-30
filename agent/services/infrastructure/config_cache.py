"""Config accessor — single source of truth.

Delegates to ``runtime_safety.load_config()`` (the authoritative `runtime_config.json`
loader, with defaults + secret resolution + mtime-invalidated cache). Historically this
read a *separate* ``services/config.json`` which does not exist in this tree, so it
silently returned ``{}`` to every importer. Consolidated 2026-06-30 (R3) to remove the
config drift and that empty-config bug. A legacy-file fallback remains only for resilience
if ``runtime_safety`` can't be imported.
"""
import json
import threading
from pathlib import Path

# Legacy fallback (kept only if runtime_safety is somehow unavailable at call time).
_LEGACY_PATH = Path(__file__).resolve().parent.parent / "config.json"
_lock = threading.Lock()
_legacy_cache = {"mtime": 0.0, "data": {}}


def get_config() -> dict:
    """Return the authoritative runtime config (runtime_config.json)."""
    try:
        import runtime_safety
        return runtime_safety.load_config()
    except Exception:
        return _legacy_get_config()


def _legacy_get_config() -> dict:
    try:
        mtime = _LEGACY_PATH.stat().st_mtime
    except OSError:
        return {}
    with _lock:
        if mtime != _legacy_cache["mtime"]:
            try:
                _legacy_cache["data"] = json.loads(_LEGACY_PATH.read_text(encoding="utf-8"))
                _legacy_cache["mtime"] = mtime
            except Exception:
                pass
        return dict(_legacy_cache["data"])


def get(key: str, default=None):
    return get_config().get(key, default)
