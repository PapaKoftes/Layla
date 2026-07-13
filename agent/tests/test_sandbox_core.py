"""Tests for the sandbox containment primitive (layla/tools/sandbox_core.py).

inside_sandbox underlies every file tool, so its containment must be airtight:
allow paths within the sandbox, reject traversal and absolute paths outside.
"""
import sys
from pathlib import Path

AGENT_DIR = Path(__file__).resolve().parent.parent
if str(AGENT_DIR) not in sys.path:
    sys.path.insert(0, str(AGENT_DIR))

import os  # noqa: E402

import pytest  # noqa: E402

from layla.tools.sandbox_core import (  # noqa: E402
    _get_sandbox,
    inside_sandbox,
    set_effective_sandbox,
)


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


@pytest.mark.parametrize(
    "spelling",
    [
        lambda h: str(h) + os.sep,          # trailing separator
        lambda h: str(h) + os.sep + os.sep,  # doubled trailing separator
        lambda h: str(h).swapcase(),        # different drive-letter / path casing
        lambda h: str(h / "subdir" / ".."),  # '..' that resolves back to home
    ],
)
def test_rejects_home_as_sandbox_root_regardless_of_spelling(spelling, monkeypatch):
    """The home-dir containment guard must reject any sandbox_root that RESOLVES to
    the user's home directory, not just a byte-identical string. A trailing
    separator, alternate casing, or a '..' spelling previously slipped past the
    raw str==str check and made the entire home tree the sandbox."""
    import runtime_safety

    home = Path.home()
    root_str = spelling(home)
    # Only meaningful when the spelling is NOT byte-identical to str(home) yet still
    # resolves to home — that's exactly the evasion the old guard missed.
    if os.path.normcase(str(Path(root_str).expanduser().resolve())) != os.path.normcase(
        str(home.resolve())
    ):
        pytest.skip("spelling does not resolve to home on this platform")

    monkeypatch.setattr(runtime_safety, "load_config", lambda: {"sandbox_root": root_str})
    # Clear any cached sandbox for this thread and ensure no thread-local shortcut.
    set_effective_sandbox(None)
    try:
        with pytest.raises(RuntimeError):
            _get_sandbox()
    finally:
        set_effective_sandbox(None)
