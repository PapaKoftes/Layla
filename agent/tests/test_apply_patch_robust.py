"""BL-108: content-verified diff-edit — apply_patch relocates fuzzy hunks + refuses mismatches."""
from __future__ import annotations

from pathlib import Path

from layla.tools.impl import file_ops


def _patch_guards(monkeypatch, target: Path):
    monkeypatch.setattr(file_ops, "_resolve_sandboxed_path", lambda p: target)
    monkeypatch.setattr(file_ops, "_ensure_inside_sandbox", lambda t: (True, None))
    monkeypatch.setattr(file_ops, "_check_read_freshness", lambda t: "")
    monkeypatch.setattr(file_ops, "_maybe_file_checkpoint", lambda t, why: None)
    monkeypatch.setattr(file_ops, "_clear_read_freshness", lambda t: None)


# ── core locator ───────────────────────────────────────────────────────────

def test_locate_block_exact_fuzzy_and_missing():
    lines = ["a\n", "b\n", "  c\n", "d\n"]
    assert file_ops._locate_block(lines, ["b\n", "  c\n"], hint=1) == 1        # exact
    assert file_ops._locate_block(lines, ["b\n", "c\n"], hint=0) == 1          # whitespace-normalized
    assert file_ops._locate_block(lines, ["zzz\n"], hint=0) is None           # absent
    # nearest-to-hint tie-break among identical candidates
    assert file_ops._locate_block(["x\n", "x\n", "x\n"], ["x\n"], hint=2) == 2
    # empty block (pure insertion) → clamped hint
    assert file_ops._locate_block(lines, [], hint=2) == 2


_FILE = "line1\nline2\nline3\nline4\nline5\n"


def test_apply_patch_clean(tmp_path, monkeypatch):
    f = tmp_path / "f.txt"
    f.write_text(_FILE, encoding="utf-8")
    _patch_guards(monkeypatch, f)
    patch = "--- a/f.txt\n+++ b/f.txt\n@@ -2,3 +2,3 @@\n line2\n-line3\n+LINE3\n line4\n"
    res = file_ops.apply_patch("f.txt", patch)
    assert res["ok"] is True and res["hunks_applied"] == 1
    assert f.read_text(encoding="utf-8") == "line1\nline2\nLINE3\nline4\nline5\n"


def test_apply_patch_relocates_wrong_line_numbers(tmp_path, monkeypatch):
    f = tmp_path / "f.txt"
    f.write_text(_FILE, encoding="utf-8")
    _patch_guards(monkeypatch, f)
    # Declared at L40 (nonsense), but the context lines live at L2 → must relocate + apply,
    # NOT blindly delete line 40 (which doesn't exist) or corrupt the file.
    patch = "--- a/f.txt\n+++ b/f.txt\n@@ -40,3 +40,3 @@\n line2\n-line3\n+FIXED\n line4\n"
    res = file_ops.apply_patch("f.txt", patch)
    assert res["ok"] is True
    assert f.read_text(encoding="utf-8") == "line1\nline2\nFIXED\nline4\nline5\n"


def test_apply_patch_rejects_nonmatching_without_corruption(tmp_path, monkeypatch):
    f = tmp_path / "f.txt"
    f.write_text(_FILE, encoding="utf-8")
    _patch_guards(monkeypatch, f)
    patch = "--- a/f.txt\n+++ b/f.txt\n@@ -2,3 +2,3 @@\n nonexistent_ctx\n-also_missing\n+new\n more_missing\n"
    res = file_ops.apply_patch("f.txt", patch)
    assert res["ok"] is False and "did not match" in res["error"]
    assert f.read_text(encoding="utf-8") == _FILE            # file UNCHANGED — no corruption
