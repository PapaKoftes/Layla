"""Tests for services/knowledge_watcher.py."""
from __future__ import annotations

import hashlib
import os
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from services.knowledge_watcher import (
    SKIP_PATTERNS,
    SUPPORTED_EXTENSIONS,
    KnowledgeWatcher,
    _FileTracker,
    _file_hash,
    _should_process,
)


# ── SUPPORTED_EXTENSIONS / SKIP_PATTERNS ───────────────────────────────


def test_supported_extensions_contains_expected_types():
    for ext in (".py", ".md", ".txt", ".json", ".pdf", ".docx", ".yaml", ".csv"):
        assert ext in SUPPORTED_EXTENSIONS, f"{ext} missing from SUPPORTED_EXTENSIONS"


def test_skip_patterns_contains_expected_entries():
    for pat in ("__pycache__", ".git", "node_modules", ".pyc"):
        assert pat in SKIP_PATTERNS, f"{pat} missing from SKIP_PATTERNS"


# ── _should_process ────────────────────────────────────────────────────


def test_should_process_returns_true_for_supported_extension(tmp_path: Path):
    f = tmp_path / "readme.md"
    f.write_text("hello")
    assert _should_process(f) is True


def test_should_process_returns_false_for_unsupported_extension(tmp_path: Path):
    f = tmp_path / "archive.zip"
    f.write_bytes(b"\x00" * 10)
    assert _should_process(f) is False


def test_should_process_skips_pycache(tmp_path: Path):
    cache_dir = tmp_path / "__pycache__"
    cache_dir.mkdir()
    f = cache_dir / "module.py"
    f.write_text("x = 1")
    assert _should_process(f) is False


def test_should_process_skips_git_directory(tmp_path: Path):
    git_dir = tmp_path / ".git"
    git_dir.mkdir()
    f = git_dir / "config.json"
    f.write_text("{}")
    assert _should_process(f) is False


def test_should_process_skips_node_modules(tmp_path: Path):
    nm = tmp_path / "node_modules"
    nm.mkdir()
    f = nm / "index.js"
    f.write_text("module.exports = {};")
    assert _should_process(f) is False


def test_should_process_skips_large_files(tmp_path: Path):
    """Files over 50 MB should be rejected."""
    f = tmp_path / "huge.txt"
    f.write_text("x")
    # Patch stat to report >50MB
    original_stat = f.stat

    class FakeStat:
        def __init__(self, real):
            self._real = real

        def __getattr__(self, name):
            return getattr(self._real, name)

        @property
        def st_size(self):
            return 51 * 1024 * 1024

    with patch.object(type(f), "stat", return_value=FakeStat(original_stat())):
        assert _should_process(f) is False


def test_should_process_rejects_non_file(tmp_path: Path):
    d = tmp_path / "subdir"
    d.mkdir()
    assert _should_process(d) is False


# ── _file_hash ─────────────────────────────────────────────────────────


def test_file_hash_returns_16_char_hex(tmp_path: Path):
    f = tmp_path / "data.txt"
    f.write_text("some content")
    result = _file_hash(f)
    assert len(result) == 16
    assert all(c in "0123456789abcdef" for c in result)


def test_file_hash_matches_sha256_prefix(tmp_path: Path):
    f = tmp_path / "data.txt"
    content = b"hello world"
    f.write_bytes(content)
    expected = hashlib.sha256(content).hexdigest()[:16]
    assert _file_hash(f) == expected


def test_file_hash_returns_empty_on_missing_file():
    result = _file_hash(Path("/nonexistent/file.txt"))
    assert result == ""


# ── _FileTracker ───────────────────────────────────────────────────────


def test_tracker_has_changed_true_for_new_file(tmp_path: Path):
    f = tmp_path / "new.txt"
    f.write_text("brand new")
    tracker = _FileTracker()
    assert tracker.has_changed(f) is True


def test_tracker_has_changed_false_for_same_content(tmp_path: Path):
    f = tmp_path / "stable.txt"
    f.write_text("unchanged")
    tracker = _FileTracker()
    tracker.has_changed(f)  # first call registers hash
    assert tracker.has_changed(f) is False


def test_tracker_has_changed_true_when_content_changes(tmp_path: Path):
    f = tmp_path / "mutable.txt"
    f.write_text("version 1")
    tracker = _FileTracker()
    tracker.has_changed(f)
    f.write_text("version 2")
    assert tracker.has_changed(f) is True


def test_tracker_mark_processed_updates_hash(tmp_path: Path):
    f = tmp_path / "doc.txt"
    f.write_text("original")
    tracker = _FileTracker()
    tracker.mark_processed(f)
    # After mark_processed, has_changed should return False for same content
    assert tracker.has_changed(f) is False


# ── KnowledgeWatcher.__init__ ──────────────────────────────────────────


@patch("services.knowledge_watcher.KnowledgeWatcher._load_config")
def test_init_empty_config_has_no_watch_dirs(mock_load):
    watcher = KnowledgeWatcher({})
    assert watcher._watch_dirs == []


# ── add_watch_dir / remove_watch_dir ───────────────────────────────────


@patch("services.knowledge_watcher.KnowledgeWatcher._load_config")
def test_add_watch_dir_valid_directory(mock_load, tmp_path: Path):
    watcher = KnowledgeWatcher({})
    assert watcher.add_watch_dir(str(tmp_path)) is True
    assert tmp_path in watcher._watch_dirs


@patch("services.knowledge_watcher.KnowledgeWatcher._load_config")
def test_add_watch_dir_rejects_nonexistent(mock_load):
    watcher = KnowledgeWatcher({})
    assert watcher.add_watch_dir("/does/not/exist/at/all") is False
    assert len(watcher._watch_dirs) == 0


@patch("services.knowledge_watcher.KnowledgeWatcher._load_config")
def test_remove_watch_dir_existing(mock_load, tmp_path: Path):
    watcher = KnowledgeWatcher({})
    watcher.add_watch_dir(str(tmp_path))
    assert watcher.remove_watch_dir(str(tmp_path)) is True
    assert tmp_path not in watcher._watch_dirs


@patch("services.knowledge_watcher.KnowledgeWatcher._load_config")
def test_remove_watch_dir_returns_false_if_missing(mock_load):
    watcher = KnowledgeWatcher({})
    assert watcher.remove_watch_dir("/never/added") is False


# ── get_stats ──────────────────────────────────────────────────────────


@patch("services.knowledge_watcher.KnowledgeWatcher._load_config")
def test_get_stats_structure(mock_load, tmp_path: Path):
    watcher = KnowledgeWatcher({})
    watcher.add_watch_dir(str(tmp_path))
    stats = watcher.get_stats()
    assert "running" in stats
    assert "watch_dirs" in stats
    assert "exclude_dirs" in stats
    assert "files_ingested" in stats
    assert "files_skipped" in stats
    assert "mode" in stats
    assert stats["running"] is False
    assert stats["files_ingested"] == 0


# ── start ──────────────────────────────────────────────────────────────


@patch("services.knowledge_watcher.KnowledgeWatcher._load_config")
def test_start_returns_false_when_no_watch_dirs(mock_load):
    watcher = KnowledgeWatcher({})
    assert watcher.start() is False


# ── _should_ingest ─────────────────────────────────────────────────────


@patch("services.knowledge_watcher.KnowledgeWatcher._load_config")
def test_should_ingest_returns_true_with_no_governor(mock_load):
    """When resource_governor import fails, _should_ingest defaults to True."""
    watcher = KnowledgeWatcher({})
    # Force the import to fail so the except branch (return True) is taken
    with patch.dict(sys.modules, {"services.resource_governor": None}):
        assert watcher._should_ingest() is True


@patch("services.knowledge_watcher.KnowledgeWatcher._load_config")
def test_should_ingest_returns_true_for_breathe_mode(mock_load):
    watcher = KnowledgeWatcher({})
    mock_mode = MagicMock()
    mock_mode.value = "breathe"
    with patch("services.resource_governor.get_mode", return_value=mock_mode):
        assert watcher._should_ingest() is True


@patch("services.knowledge_watcher.KnowledgeWatcher._load_config")
def test_should_ingest_returns_false_for_hibernate_mode(mock_load):
    watcher = KnowledgeWatcher({})
    mock_mode = MagicMock()
    mock_mode.value = "hibernate"
    with patch("services.resource_governor.get_mode", return_value=mock_mode):
        assert watcher._should_ingest() is False


# ── scan_now ───────────────────────────────────────────────────────────


@patch("services.knowledge_watcher.KnowledgeWatcher._load_config")
def test_scan_now_processes_files_in_watched_dirs(mock_load, tmp_path: Path):
    """scan_now should find and attempt to process supported files."""
    watcher = KnowledgeWatcher({})
    watcher.add_watch_dir(str(tmp_path))

    # Create some test files
    (tmp_path / "readme.md").write_text("# Hello")
    (tmp_path / "script.py").write_text("print('hi')")
    (tmp_path / "image.png").write_bytes(b"\x89PNG")  # unsupported

    # Patch _ingest_file so we don't need the full ingestion pipeline
    ingested = []

    def fake_ingest(path: Path):
        ingested.append(path.name)
        watcher._files_ingested += 1
        watcher._tracker.mark_processed(path)

    watcher._ingest_file = fake_ingest

    # Patch _should_ingest to allow processing regardless of governor mode
    with patch.object(watcher, "_should_ingest", return_value=True):
        result = watcher.scan_now()
    assert result["files_ingested"] >= 2
    assert "readme.md" in ingested
    assert "script.py" in ingested
    assert "image.png" not in ingested
