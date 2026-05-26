"""Single-source config.json loader with mtime-invalidated cache."""
import json
import threading
from pathlib import Path

_CFG_PATH = Path(__file__).resolve().parent.parent / "config.json"
_lock = threading.Lock()
_cache = {"mtime": 0.0, "data": {}}


def get_config() -> dict:
    """Return cached config.json content; reload only when mtime changes."""
    try:
        mtime = _CFG_PATH.stat().st_mtime
    except OSError:
        return {}
    with _lock:
        if mtime != _cache["mtime"]:
            try:
                _cache["data"] = json.loads(_CFG_PATH.read_text(encoding="utf-8"))
                _cache["mtime"] = mtime
            except Exception:
                pass
        return dict(_cache["data"])


def get(key: str, default=None):
    return get_config().get(key, default)
