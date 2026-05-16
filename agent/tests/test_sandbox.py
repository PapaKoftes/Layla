"""Tests for sandbox path checking in layla/tools/registry.py."""
import os
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def _make_sandbox(tmp_path):
    """Patch _get_sandbox to return tmp_path."""
    from layla.tools import sandbox_core
    return patch.object(sandbox_core, "_get_sandbox", return_value=tmp_path.resolve())


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
        with patch("layla.tools.sandbox_core._get_sandbox", return_value=sandbox.resolve()):
            from layla.tools.registry import inside_sandbox
            assert inside_sandbox(foobar) is False

    def test_sibling_dir(self, tmp_path):
        child = tmp_path / "child"
        child.mkdir()
        sibling = tmp_path / "child2"
        with _make_sandbox(child):
            from layla.tools.registry import inside_sandbox
            assert inside_sandbox(sibling) is False


@pytest.mark.skipif(bool(os.environ.get("CI")), reason="CI has explicit runtime_config.json")
class TestSandboxRootDefault:
    def test_sandbox_root_default_is_layla_workspace(self):
        """sandbox_root default must be ~/layla-workspace, not ~."""
        from pathlib import Path
        from unittest.mock import patch

        import runtime_safety as rs

        expected_default = str(Path.home() / "layla-workspace")

        # Patch at the module level (json.loads and CONFIG_FILE.stat via builtins)
        with patch.object(rs, "_config_cache", None):
            rs._config_cache = None
            rs._config_last_check = 0.0
            # Force fallback path: patch json.loads to raise so config file isn't loaded
            import builtins
            orig_open = builtins.open

            def mock_open(file, *args, **kwargs):
                if "runtime_config" in str(file):
                    raise FileNotFoundError("no config")
                return orig_open(file, *args, **kwargs)

            with patch("builtins.open", side_effect=mock_open):
                with patch("pathlib.Path.mkdir", return_value=None):
                    with patch("pathlib.Path.stat", side_effect=FileNotFoundError):
                        rs._config_cache = None
                        rs._config_last_check = 0.0
                        cfg = rs.load_config()

        assert cfg["sandbox_root"] == expected_default, (
            f"sandbox_root should be {expected_default!r}, got {cfg['sandbox_root']!r}"
        )

    def test_sandbox_root_not_bare_home(self):
        """sandbox_root default must NOT be the bare home directory."""
        import builtins
        from pathlib import Path
        from unittest.mock import patch

        import runtime_safety as rs

        orig_open = builtins.open

        def mock_open(file, *args, **kwargs):
            if "runtime_config" in str(file):
                raise FileNotFoundError("no config")
            return orig_open(file, *args, **kwargs)

        with patch("builtins.open", side_effect=mock_open):
            with patch("pathlib.Path.mkdir", return_value=None):
                with patch("pathlib.Path.stat", side_effect=FileNotFoundError):
                    rs._config_cache = None
                    rs._config_last_check = 0.0
                    cfg = rs.load_config()

        assert cfg["sandbox_root"] != str(Path.home()), (
            "sandbox_root should not default to bare home directory"
        )
