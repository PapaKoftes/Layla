"""Regressions for the v1.7.5 end-to-end verification audit fixes.

- add_vector must RAISE on a store-write failure (not swallow + return a fake id), so callers' needs_reindex
  recovery fires instead of orphaning a learning.
- POST /settings/themes must block a REMOTE write to a security-critical theme flag (plugins_enabled etc.),
  matching POST /settings — else remote clients bypass _REMOTE_PROTECTED_KEYS.
- POST /obsidian/writeback must not 500 on a non-numeric `n`.
"""
import sys
from pathlib import Path

import pytest

AGENT_DIR = Path(__file__).resolve().parent.parent
if str(AGENT_DIR) not in sys.path:
    sys.path.insert(0, str(AGENT_DIR))


def test_add_vector_raises_on_store_failure(monkeypatch):
    import numpy as np

    from layla.memory import vector_store as vs

    class _BoomColl:
        def add(self, *a, **k):
            raise RuntimeError("database is locked")

    monkeypatch.setattr(vs, "_get_chroma_collection", lambda: _BoomColl())
    with pytest.raises(Exception):  # noqa: B017 — the point is it no longer silently returns a fake uid
        vs.add_vector(np.zeros(8, dtype="float32"), {"content": "x", "type": "fact"})


def _client():
    from fastapi.testclient import TestClient

    from main import app
    return TestClient(app)


def test_settings_themes_blocks_remote_protected_flag(monkeypatch):
    """A remote caller (is_direct_local False) cannot enable the external_tools theme, whose flags include
    plugins_enabled (the plugin CODE-EXECUTION gate)."""
    import services.safety.auth as auth
    monkeypatch.setattr(auth, "is_direct_local", lambda *a, **k: False)
    with _client() as c:
        r = c.post("/settings/themes", json={"key": "external_tools", "enabled": True})
    assert r.status_code == 403, r.text
    body = r.json()
    assert body.get("ok") is False
    assert "plugins_enabled" in (body.get("protected_keys") or [])


def test_settings_themes_allows_local_protected_flag(monkeypatch):
    """A LOCAL caller is still allowed to toggle the same theme (not a blanket block)."""
    import services.safety.auth as auth
    monkeypatch.setattr(auth, "is_direct_local", lambda *a, **k: True)
    with _client() as c:
        r = c.post("/settings/themes", json={"key": "external_tools", "enabled": False})
    assert r.status_code == 200, r.text


def test_obsidian_writeback_non_numeric_n_is_not_500():
    with _client() as c:
        r = c.post("/obsidian/writeback", json={"n": "abc"})
    # Disabled-by-default -> clean 403; the point is it must NOT be a 500 from int("abc").
    assert r.status_code != 500, r.text
