"""Phase 5.1 — Obsidian vault sync tests."""
import pytest
from pathlib import Path


@pytest.fixture
def vault(tmp_path):
    v = tmp_path / "vault"
    v.mkdir()
    (v / "note1.md").write_text("# Note 1\nHello vault", encoding="utf-8")
    (v / "sub").mkdir()
    (v / "sub" / "note2.md").write_text("# Note 2\nNested note", encoding="utf-8")
    # Hidden dir should be skipped
    (v / ".trash").mkdir()
    (v / ".trash" / "hidden.md").write_text("should skip", encoding="utf-8")
    return v


@pytest.fixture
def repo_root(tmp_path):
    return tmp_path


def test_set_vault_path_valid(vault):
    from services.obsidian_sync import set_vault_path, get_vault_path, _vault_config
    _vault_config.clear()
    result = set_vault_path(str(vault))
    assert result["ok"] is True
    assert get_vault_path() == vault


def test_set_vault_path_invalid(tmp_path):
    from services.obsidian_sync import set_vault_path
    result = set_vault_path(str(tmp_path / "nonexistent"))
    assert result["ok"] is False
    assert "error" in result


def test_md_files_excludes_hidden(vault):
    from services.obsidian_sync import _md_files
    files = _md_files(vault)
    paths = [str(f) for f in files]
    assert any("note1.md" in p for p in paths)
    assert any("note2.md" in p for p in paths)
    assert not any(".trash" in p for p in paths)


def test_diff_vault_new_files(vault, repo_root):
    from services.obsidian_sync import _vault_config, diff_vault, set_vault_path
    _vault_config.clear()
    set_vault_path(str(vault))
    result = diff_vault(repo_root)
    assert result["ok"] is True
    assert len(result["new"]) == 2  # note1.md + sub/note2.md
    assert result["updated"] == []
    assert result["unchanged"] == []


def test_sync_vault_copies_files(vault, repo_root):
    from services.obsidian_sync import _vault_config, get_knowledge_vault_dir, set_vault_path, sync_vault
    _vault_config.clear()
    set_vault_path(str(vault))
    result = sync_vault(repo_root)
    assert result["ok"] is True
    assert result["copied"] == 2
    dest = get_knowledge_vault_dir(repo_root)
    assert (dest / "note1.md").exists()
    assert (dest / "sub" / "note2.md").exists()


def test_sync_vault_skips_conflict(vault, repo_root):
    """Files where dest is newer (and content differs) are skipped unless force=True."""
    import time
    from services.obsidian_sync import _vault_config, get_knowledge_vault_dir, set_vault_path, sync_vault
    _vault_config.clear()
    set_vault_path(str(vault))
    # First sync
    sync_vault(repo_root)
    dest = get_knowledge_vault_dir(repo_root)
    # Make dest newer with different content
    dst_file = dest / "note1.md"
    dst_file.write_text("# Modified in knowledge", encoding="utf-8")
    # Ensure dst mtime is ahead of src
    import os
    future_time = time.time() + 10
    os.utime(dst_file, (future_time, future_time))
    # Sync again (no force) — should skip conflict
    result = sync_vault(repo_root)
    assert result["skipped_conflicts"] >= 1


def test_sync_vault_force_overwrites_conflict(vault, repo_root):
    import os, time
    from services.obsidian_sync import _vault_config, get_knowledge_vault_dir, set_vault_path, sync_vault
    _vault_config.clear()
    set_vault_path(str(vault))
    sync_vault(repo_root)
    dest = get_knowledge_vault_dir(repo_root)
    dst_file = dest / "note1.md"
    dst_file.write_text("modified", encoding="utf-8")
    future_time = time.time() + 10
    os.utime(dst_file, (future_time, future_time))
    result = sync_vault(repo_root, force=True)
    assert result["copied"] >= 1
    # Content should be restored to vault version
    assert "Hello vault" in dst_file.read_text(encoding="utf-8")


def test_diff_after_sync_shows_unchanged(vault, repo_root):
    from services.obsidian_sync import _vault_config, diff_vault, set_vault_path, sync_vault
    _vault_config.clear()
    set_vault_path(str(vault))
    sync_vault(repo_root)
    result = diff_vault(repo_root)
    assert result["unchanged"] == ["note1.md", "sub/note2.md"] or len(result["unchanged"]) == 2


def test_suggest_export_returns_structure(monkeypatch):
    """suggest_export returns correct shape even with no DB."""
    monkeypatch.setattr(
        "services.obsidian_sync.get_vault_path",
        lambda: None,
    )
    # Patch DB call to return fake learnings
    monkeypatch.setattr(
        "layla.memory.db.get_top_learnings_for_planning",
        lambda limit, min_confidence: [
            {"id": "1", "content": "Always test edge cases.", "type": "strategy", "confidence": 0.9}
        ],
    )
    from services.obsidian_sync import suggest_export
    result = suggest_export(n=5)
    assert result["ok"] is True
    assert result["count"] == 1
    note = result["suggestions"][0]
    assert "note_md" in note
    assert "filename" in note
    assert note["filename"].startswith("layla-")
    assert "Always test edge cases" in note["note_md"]


def test_export_to_vault_requires_connection(monkeypatch):
    monkeypatch.setattr("services.obsidian_sync.get_vault_path", lambda: None)
    from services.obsidian_sync import export_to_vault
    result = export_to_vault(["1"])
    assert result["ok"] is False
    assert "No vault path" in result["error"]
