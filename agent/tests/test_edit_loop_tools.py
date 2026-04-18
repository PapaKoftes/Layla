"""Edit-loop helpers: batch write resolution, deterministic verify hooks."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

AGENT_DIR = Path(__file__).resolve().parent.parent
if str(AGENT_DIR) not in sys.path:
    sys.path.insert(0, str(AGENT_DIR))


def test_write_files_batch_resolves_relative_paths(tmp_path: Path) -> None:
    from layla.tools.impl import file_ops
    from layla.tools.registry import set_effective_sandbox

    set_effective_sandbox(str(tmp_path))
    try:
        out = file_ops.write_files_batch([{"path": "foo/x.txt", "content": "hello"}])
        assert out.get("ok") is True
        p = tmp_path / "foo" / "x.txt"
        assert p.is_file()
        assert p.read_text(encoding="utf-8") == "hello"
    finally:
        set_effective_sandbox(None)


def test_det_verify_search_replace_literal(tmp_path: Path) -> None:
    from services.tool_output_validator import deterministic_verify_tool_result

    f = tmp_path / "a.py"
    f.write_text("aaa\n", encoding="utf-8")
    ok_res = {
        "ok": True,
        "dry_run": False,
        "find": "aaa",
        "use_regex": False,
        "matches": [{"path": str(f), "count": 1}],
    }
    vr = deterministic_verify_tool_result("search_replace", ok_res, workspace_root=str(tmp_path))
    assert vr.get("ok") is False

    f.write_text("bbb\n", encoding="utf-8")
    vr2 = deterministic_verify_tool_result("search_replace", ok_res, workspace_root=str(tmp_path))
    assert vr2.get("ok") is True
