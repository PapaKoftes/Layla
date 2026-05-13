"""Tests for skill pack sandbox (venv isolation)."""
import pytest
import sys
from pathlib import Path
from unittest.mock import patch, MagicMock


class TestVenvPaths:
    def test_venv_dir(self):
        from services.skill_sandbox import _venv_dir
        d = _venv_dir("my-pack")
        assert "my-pack" in str(d)
        assert ".layla" in str(d)

    def test_venv_python_windows(self):
        from services.skill_sandbox import _venv_python
        with patch("services.skill_sandbox.sys") as mock_sys:
            mock_sys.platform = "win32"
            p = _venv_python("test")
            # Check it has the right structure
            assert isinstance(p, Path)

    def test_venv_python_unix(self):
        from services.skill_sandbox import _venv_python
        with patch("services.skill_sandbox.sys") as mock_sys:
            mock_sys.platform = "linux"
            p = _venv_python("test")
            assert isinstance(p, Path)


class TestCreateVenv:
    def test_create_venv(self, tmp_path):
        from services.skill_sandbox import create_venv
        import services.skill_sandbox as ss
        old_dir = ss.ENVS_DIR
        ss.ENVS_DIR = tmp_path / "envs"
        try:
            ok, msg = create_venv("test-pack")
            assert ok is True
            assert "created" in msg.lower() or "exists" in msg.lower()
        finally:
            ss.ENVS_DIR = old_dir

    def test_create_existing_is_ok(self, tmp_path):
        from services.skill_sandbox import create_venv
        import services.skill_sandbox as ss
        old_dir = ss.ENVS_DIR
        ss.ENVS_DIR = tmp_path / "envs"
        try:
            create_venv("existing")
            ok, msg = create_venv("existing")
            assert ok is True
        finally:
            ss.ENVS_DIR = old_dir


class TestRunEntryPoint:
    def test_missing_venv(self, tmp_path):
        from services.skill_sandbox import run_entry_point
        result = run_entry_point("nonexistent", tmp_path, "main.py")
        assert result["ok"] is False
        assert "not found" in result["stderr"].lower()

    def test_missing_entry_point(self, tmp_path):
        from services.skill_sandbox import run_entry_point, create_venv
        import services.skill_sandbox as ss
        old_dir = ss.ENVS_DIR
        ss.ENVS_DIR = tmp_path / "envs"
        try:
            create_venv("entry-test")
            result = run_entry_point("entry-test", tmp_path, "nonexistent.py")
            assert result["ok"] is False
            assert "not found" in result["stderr"].lower()
        finally:
            ss.ENVS_DIR = old_dir

    def test_successful_run(self, tmp_path):
        from services.skill_sandbox import run_entry_point, create_venv
        import services.skill_sandbox as ss
        old_dir = ss.ENVS_DIR
        ss.ENVS_DIR = tmp_path / "envs"
        try:
            create_venv("run-test")
            # Create a simple entry point
            pack_dir = tmp_path / "pack"
            pack_dir.mkdir()
            (pack_dir / "main.py").write_text('print("hello from skill")')
            result = run_entry_point("run-test", pack_dir, "main.py")
            assert result["ok"] is True
            assert "hello from skill" in result["stdout"]
            assert result["timed_out"] is False
        finally:
            ss.ENVS_DIR = old_dir

    def test_timeout(self, tmp_path):
        from services.skill_sandbox import run_entry_point, create_venv
        import services.skill_sandbox as ss
        old_dir = ss.ENVS_DIR
        ss.ENVS_DIR = tmp_path / "envs"
        try:
            create_venv("timeout-test")
            pack_dir = tmp_path / "pack"
            pack_dir.mkdir()
            (pack_dir / "slow.py").write_text('import time; time.sleep(60)')
            result = run_entry_point("timeout-test", pack_dir, "slow.py", timeout_seconds=2)
            assert result["ok"] is False
            assert result["timed_out"] is True
        finally:
            ss.ENVS_DIR = old_dir

    def test_env_variables(self, tmp_path):
        from services.skill_sandbox import run_entry_point, create_venv
        import services.skill_sandbox as ss
        old_dir = ss.ENVS_DIR
        ss.ENVS_DIR = tmp_path / "envs"
        try:
            create_venv("env-test")
            pack_dir = tmp_path / "pack"
            pack_dir.mkdir()
            (pack_dir / "env.py").write_text(
                'import os; print(os.environ.get("LAYLA_SKILL_PACK", "MISSING"))'
            )
            result = run_entry_point("env-test", pack_dir, "env.py")
            assert result["ok"] is True
            assert "env-test" in result["stdout"]
        finally:
            ss.ENVS_DIR = old_dir


class TestRemoveVenv:
    def test_remove_existing(self, tmp_path):
        from services.skill_sandbox import create_venv, remove_venv, venv_exists
        import services.skill_sandbox as ss
        old_dir = ss.ENVS_DIR
        ss.ENVS_DIR = tmp_path / "envs"
        try:
            create_venv("removable")
            ok, _ = remove_venv("removable")
            assert ok is True
        finally:
            ss.ENVS_DIR = old_dir

    def test_remove_nonexistent(self, tmp_path):
        from services.skill_sandbox import remove_venv
        import services.skill_sandbox as ss
        old_dir = ss.ENVS_DIR
        ss.ENVS_DIR = tmp_path / "envs"
        try:
            ok, _ = remove_venv("ghost")
            assert ok is True
        finally:
            ss.ENVS_DIR = old_dir


class TestListVenvs:
    def test_list_empty(self, tmp_path):
        from services.skill_sandbox import list_venvs
        import services.skill_sandbox as ss
        old_dir = ss.ENVS_DIR
        ss.ENVS_DIR = tmp_path / "envs"
        try:
            assert list_venvs() == []
        finally:
            ss.ENVS_DIR = old_dir

    def test_list_after_create(self, tmp_path):
        from services.skill_sandbox import create_venv, list_venvs
        import services.skill_sandbox as ss
        old_dir = ss.ENVS_DIR
        ss.ENVS_DIR = tmp_path / "envs"
        try:
            create_venv("listed-pack")
            venvs = list_venvs()
            assert "listed-pack" in venvs
        finally:
            ss.ENVS_DIR = old_dir
