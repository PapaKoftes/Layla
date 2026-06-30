"""Tests for the sandbox containment primitive (layla/tools/sandbox_core.py).

inside_sandbox underlies every file tool, so its containment must be airtight:
allow paths within the sandbox, reject traversal and absolute paths outside.
"""
import sys
from pathlib import Path

AGENT_DIR = Path(__file__).resolve().parent.parent
if str(AGENT_DIR) not in sys.path:
    sys.path.insert(0, str(AGENT_DIR))

from layla.tools.sandbox_core import inside_sandbox, set_effective_sandbox  # noqa: E402


def test_allows_paths_inside(tmp_path):
    set_effective_sandbox(str(tmp_path))
    try:
        assert inside_sandbox(tmp_path) is True               # the root itself
        assert inside_sandbox(tmp_path / "a" / "b.txt") is True
        assert inside_sandbox(tmp_path / "deep" / "nested" / "f") is True
    finally:
        set_effective_sandbox(None)


def test_blocks_dotdot_traversal(tmp_path):
    sb = tmp_path / "sandbox"
    sb.mkdir()
    set_effective_sandbox(str(sb))
    try:
        assert inside_sandbox(sb / ".." / "escape.txt") is False
        assert inside_sandbox(sb / "x" / ".." / ".." / "escape.txt") is False
        assert inside_sandbox(tmp_path / "sibling.txt") is False
    finally:
        set_effective_sandbox(None)


def test_blocks_absolute_outside(tmp_path):
    set_effective_sandbox(str(tmp_path))
    try:
        other = Path("C:/Windows/System32/drivers/etc/hosts") if sys.platform == "win32" else Path("/etc/passwd")
        assert inside_sandbox(other) is False
    finally:
        set_effective_sandbox(None)
