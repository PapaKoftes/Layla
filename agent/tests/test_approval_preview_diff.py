"""Unified diff / patch preview attached to approval payloads."""

from __future__ import annotations

import sys
from pathlib import Path

AGENT_DIR = Path(__file__).resolve().parent.parent
if str(AGENT_DIR) not in sys.path:
    sys.path.insert(0, str(AGENT_DIR))

import agent_loop  # noqa: E402


def test_approval_preview_write_file_new_file_marker(tmp_path):
    args = {"path": "new.txt", "content": "a\n"}
    agent_loop._approval_preview_diff("write_file", args, str(tmp_path))
    assert args.get("diff") == "(new file)"


def test_approval_preview_apply_patch_truncates():
    big = "\n".join(f"line {i}" for i in range(300))
    args = {"patch_text": big}
    agent_loop._approval_preview_diff("apply_patch", args, "")
    d = args.get("diff") or ""
    assert "truncated" in d or len(d.splitlines()) <= 250
