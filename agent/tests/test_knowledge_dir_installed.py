"""Knowledge root on an INSTALLED build: the install dir (C:\\Program Files\\Layla) is read-only for a normal
user, so every feature that wrote under ``<install>/knowledge`` failed there — fetch_url(store=True), crawl
"save to knowledge" (silently: bare except), chat import, doc ingestion, the Obsidian vault, memory-backup
import. runtime_safety.knowledge_dir() is now the single owner: unchanged on a source checkout, per-user
``<LAYLA_DATA_DIR>/knowledge`` (seeded from the shipped tree) when the install dir isn't writable.

These tests simulate the installed layout: a fake install root (an installed build, see
runtime_safety.is_installed_build) plus a data dir. They drive the REAL writers and assert WHERE the bytes land.
"""
import io
import json
import os
import sys
import time
import zipfile
from pathlib import Path

import pytest

AGENT_DIR = Path(__file__).resolve().parent.parent
if str(AGENT_DIR) not in sys.path:
    sys.path.insert(0, str(AGENT_DIR))


@pytest.fixture
def installed(monkeypatch, tmp_path):
    """Fake installed build: <tmp>/install/knowledge (the shipped tree) + <tmp>/data."""
    import runtime_safety as rs

    install = tmp_path / "install"
    shipped = install / "knowledge"
    (shipped / "packs" / "core").mkdir(parents=True)
    (shipped / "packs" / "core" / "base.md").write_text("shipped core doc", encoding="utf-8")
    (shipped / "packs" / "presets.json").write_text('{"companion": ["core", "sentinelpack"]}', encoding="utf-8")
    (shipped / "loose.md").write_text("shipped loose doc", encoding="utf-8")
    data = tmp_path / "data"
    data.mkdir()

    monkeypatch.setattr(rs, "REPO_ROOT", install)
    monkeypatch.setattr(rs, "_INSTALLED", True)
    monkeypatch.setenv("LAYLA_DATA_DIR", str(data))
    monkeypatch.setattr(rs, "_KNOWLEDGE_DIR", None)  # drop the process cache; monkeypatch restores it after
    root = rs.knowledge_dir()
    assert root == data / "knowledge", f"PROBE BROKEN: resolver chose {root}"
    return {"rs": rs, "shipped": shipped, "root": root, "data": data}


def test_source_checkout_is_unchanged(monkeypatch):
    import runtime_safety as rs

    monkeypatch.setattr(rs, "_KNOWLEDGE_DIR", None)
    monkeypatch.setattr(rs, "_INSTALLED", None)
    assert rs.knowledge_dir() == rs.REPO_ROOT / "knowledge", "a source checkout keeps repo knowledge/ as the root"


def test_installed_build_detection(monkeypatch, tmp_path):
    import runtime_safety as rs

    marker = tmp_path / ".layla_installed"
    monkeypatch.setattr(rs, "INSTALL_MARKER", marker)
    monkeypatch.setenv("LAYLA_DATA_DIR", str(tmp_path / "data"))
    for present, data, expected in ((False, True, False), (True, True, True), (True, False, False)):
        if present:
            marker.write_text("x", encoding="utf-8")
        elif marker.exists():
            marker.unlink()
        if not data:
            monkeypatch.delenv("LAYLA_DATA_DIR")
        monkeypatch.setattr(rs, "_INSTALLED", None)
        assert rs.is_installed_build() is expected, (present, data)


def test_the_source_tree_is_never_marked_installed():
    import runtime_safety as rs

    assert not rs.INSTALL_MARKER.exists(), "the marker belongs only in the installer payload, never in a checkout"


def test_installed_root_is_per_user_and_seeded(installed):
    root = installed["root"]
    assert (root / "packs" / "core" / "base.md").read_text(encoding="utf-8") == "shipped core doc"
    assert (root / "loose.md").is_file() and (root / "packs" / "presets.json").is_file()


def test_sync_keeps_user_files_and_edits_but_takes_upgrades(installed):
    rs, shipped, root = installed["rs"], installed["shipped"], installed["root"]
    (root / "imports").mkdir()
    (root / "imports" / "mine.md").write_text("user import", encoding="utf-8")
    edited = root / "loose.md"
    edited.write_text("user edited", encoding="utf-8")
    future = time.time() + 60
    os.utime(edited, (future, future))                       # user edit is newer than the shipped copy
    upgraded = shipped / "packs" / "core" / "base.md"
    upgraded.write_text("release 2 core doc", encoding="utf-8")
    os.utime(upgraded, (future + 60, future + 60))           # a later release changed this shipped file

    rs._sync_shipped_knowledge(shipped, root)

    assert (root / "imports" / "mine.md").read_text(encoding="utf-8") == "user import"
    assert edited.read_text(encoding="utf-8") == "user edited"
    assert (root / "packs" / "core" / "base.md").read_text(encoding="utf-8") == "release 2 core doc"


def test_fetch_url_store_lands_in_the_per_user_root(installed, monkeypatch):
    from layla.tools import web as lweb

    class _Resp:
        headers = {"content-type": "text/html"}
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def read(self, n=None): return b"<html><body>hello from the web</body></html>"

    monkeypatch.setattr(lweb, "_is_safe_url", lambda u: True)
    monkeypatch.setattr(lweb, "_get_allowlist", lambda: [])
    monkeypatch.setattr(lweb, "_robots_allowed", lambda u: True)
    monkeypatch.setattr(lweb, "_check_ai_exclusion_headers", lambda h: False)
    monkeypatch.setattr(lweb, "_check_ai_exclusion_meta", lambda h: False)
    monkeypatch.setattr("services.safety.url_guard.safe_urlopen", lambda req, timeout=0: _Resp())

    r = lweb.fetch_url("http://example.test/page", store=True)
    assert r["ok"] is True and r["stored"], r
    stored = Path(r["stored"])
    assert stored.is_relative_to(installed["root"] / "fetched"), stored
    assert not (installed["shipped"] / "fetched").exists(), "nothing may be written into the install dir"


def test_chat_import_lands_in_the_per_user_root_and_reports_a_path(installed, monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    import routers.knowledge as rk

    app = FastAPI()
    app.include_router(rk.router)
    r = TestClient(app).post("/knowledge/import_chat", json={
        "format": "whatsapp", "title": "family",
        "text": "1/2/24, 10:00 - Ana: hi\n1/2/24, 10:01 - Ben: hello",
    })
    body = r.json()
    assert r.status_code == 200 and body.get("ok"), body
    assert body["path"] == "knowledge/imports/family.md", body
    assert (installed["root"] / "imports" / "family.md").is_file()
    assert not (installed["shipped"] / "imports").exists()


def test_memory_export_import_round_trip_uses_the_per_user_root(installed, monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    import routers.memory as rm

    monkeypatch.setattr(rm, "KNOWLEDGE_DIR", installed["root"])  # module constant is bound at import time
    app = FastAPI()
    app.include_router(rm.router)
    client = TestClient(app)

    exported = client.get("/memory/export")
    assert exported.status_code == 200, exported.text
    names = zipfile.ZipFile(io.BytesIO(exported.content)).namelist()
    assert "knowledge/packs/core/base.md" in names, names  # portable "knowledge/..." names, not data-dir paths

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("knowledge/restored/note.md", "restored note")
        zf.writestr("knowledge/../escape.md", "zip slip")
        zf.writestr("manifest.json", json.dumps({"version": 1}))
    r = client.post("/memory/import", files={"file": ("b.zip", buf.getvalue(), "application/zip")})
    assert r.status_code == 200, r.text
    assert (installed["root"] / "restored" / "note.md").read_text(encoding="utf-8") == "restored note"
    assert not (installed["data"] / "escape.md").exists(), "zip-slip guard must still hold"


def test_obsidian_vault_default_is_under_the_per_user_root(installed):
    from services.infrastructure.obsidian_sync import VAULT_SUBDIR, get_knowledge_vault_dir

    assert get_knowledge_vault_dir() == installed["root"] / VAULT_SUBDIR


def test_presets_and_packs_read_from_the_root(installed):
    from layla.memory.knowledge_packs import resolve_enabled_packs

    # sentinelpack exists ONLY in the fixture's presets.json - the built-in fallback maps companion -> core
    assert resolve_enabled_packs({"knowledge_preset": "companion"}) == {"core", "sentinelpack"}
