"""Tests for sandbox path checking in layla/tools/registry.py."""
import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def _make_sandbox(tmp_path):
    """Patch _get_sandbox to return tmp_path."""
    from layla.tools import registry
    return patch.object(registry, '_get_sandbox', return_value=tmp_path.resolve())


class TestInsideSandbox:
    def test_file_inside(self, tmp_path):
        with _make_sandbox(tmp_path):
            from layla.tools.registry import inside_sandbox
            target = tmp_path / "subdir" / "file.txt"
            assert inside_sandbox(target) is True

    def test_file_outside(self, tmp_path):
        with _make_sandbox(tmp_path):
            from layla.tools.registry import inside_sandbox
            outside = Path("/") / "etc" / "passwd"
            assert inside_sandbox(outside) is False

    def test_sandbox_root_itself(self, tmp_path):
        with _make_sandbox(tmp_path):
            from layla.tools.registry import inside_sandbox
            assert inside_sandbox(tmp_path) is True

    def test_path_traversal_attempt(self, tmp_path):
        """A traversal path like sandbox/../../etc/passwd must NOT be inside sandbox."""
        with _make_sandbox(tmp_path):
            from layla.tools.registry import inside_sandbox
            evil = tmp_path / ".." / ".." / "etc" / "passwd"
            assert inside_sandbox(evil) is False

    def test_prefix_confusion(self, tmp_path):
        """sandbox=/tmp/foo should NOT include /tmp/foobar."""
        sandbox = tmp_path / "foo"
        sandbox.mkdir()
        foobar = tmp_path / "foobar" / "file.txt"
        with patch('layla.tools.registry._get_sandbox', return_value=sandbox.resolve()):
            from layla.tools.registry import inside_sandbox
            assert inside_sandbox(foobar) is False

    def test_sibling_dir(self, tmp_path):
        child = tmp_path / "child"
        child.mkdir()
        sibling = tmp_path / "child2"
        with _make_sandbox(child):
            from layla.tools.registry import inside_sandbox
            assert inside_sandbox(sibling) is False
