"""Repo cognition: merge roots, sync stores snapshot."""
import json
import sys
import tempfile
from pathlib import Path

import pytest

AGENT_DIR = Path(__file__).resolve().parent.parent
if str(AGENT_DIR) not in sys.path:
    sys.path.insert(0, str(AGENT_DIR))


def test_merge_cognition_roots_order_and_dedupe():
    from services.repo_cognition import merge_cognition_roots

    with tempfile.TemporaryDirectory() as d1, tempfile.TemporaryDirectory() as d2:
        a = str(Path(d1).resolve())
        b = str(Path(d2).resolve())
        out = merge_cognition_roots(a, [b, b, a])
        assert out[0] == a
        assert out[1] == b
        assert len(out) == 2


def test_sync_repo_cognition_writes_snapshot(monkeypatch, tmp_path):
    from layla.memory import db as db_mod
    from services import repo_cognition as rc

    root = tmp_path / "repo"
    root.mkdir()
    (root / "README.md").write_text("# Hi\n\nPurpose.\n", encoding="utf-8")
    db_path = tmp_path / "layla.db"
    monkeypatch.setattr(db_mod, "_DB_PATH", db_path)
    monkeypatch.setattr(db_mod, "_MIGRATED", False)
    db_mod.migrate()
    out = rc.sync_repo_cognition([str(root)], index_semantic=False)
    assert out.get("ok") is True
    r0 = (out.get("results") or [{}])[0]
    assert r0.get("ok") is True
    key = db_mod.normalize_workspace_root(str(root))
    row = db_mod.get_repo_cognition_snapshot(key)
    assert row is not None
    assert "README" in (row.get("pack_markdown") or "")
    pack = json.loads(row.get("pack_json") or "{}")
    assert pack.get("fingerprint")


def test_format_cognition_missing_snapshot_hint():
    from services.repo_cognition import format_cognition_for_prompt

    with tempfile.TemporaryDirectory() as d:
        bogus = str(Path(d).resolve())
        s = format_cognition_for_prompt([bogus], max_chars=2000)
        assert "No snapshot" in s or "sync" in s.lower()
