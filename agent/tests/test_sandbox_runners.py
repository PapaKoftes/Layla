"""Sandbox subprocess runners (timeout, cwd check)."""
from pathlib import Path

import pytest


def test_python_runner_rejects_outside_sandbox(tmp_path):
    from services.sandbox.python_runner import run_python_file

    outside = tmp_path / "out"
    outside.mkdir()
    sandbox = tmp_path / "in"
    sandbox.mkdir()

    def _only_inner(p: Path) -> bool:
        try:
            p.resolve().relative_to(sandbox.resolve())
            return True
        except ValueError:
            return False

    r = run_python_file("print(1)", outside, inside_sandbox_check=_only_inner)
    assert r.get("ok") is False
    assert "sandbox" in (r.get("error") or "").lower()


def test_shell_runner_blocks_rm(tmp_path):
    from services.sandbox.shell_runner import run_shell_argv

    r = run_shell_argv(["rm", "-rf", "/"], tmp_path, inside_sandbox_check=lambda p: True)
    assert r.get("ok") is False
    assert "blocked" in (r.get("error") or "").lower()


def test_shell_runner_echo(tmp_path, monkeypatch):
    monkeypatch.setenv("PATH", "")
    from services.sandbox.shell_runner import run_shell_argv

    # Windows may not have echo as argv[0]; use Python -c
    import sys

    r = run_shell_argv([sys.executable, "-c", "print('hi')"], tmp_path, inside_sandbox_check=lambda p: True)
    assert r.get("ok") is True
    assert "hi" in (r.get("stdout") or "")
