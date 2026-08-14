"""Launcher boot-robustness regressions (launcher/layla_launcher.py).

These guard the fixes for the shipped v1.7.5 boot crash, where the engine died before /health and the
error handler then double-faulted on a None stderr, hiding the cause:
  1. _fatal must never raise — even when sys.stderr is None (the exe is built console=False).
  2. _pick_python must never hand back the frozen launcher exe itself (that yields `layla.exe -c ...`,
     which just re-runs the launcher and exits — the "engine died before health" boot failure).
"""
import importlib.util
import sys
from pathlib import Path

import pytest

_LAUNCHER = Path(__file__).resolve().parents[2] / "launcher" / "layla_launcher.py"


@pytest.fixture()
def L():
    spec = importlib.util.spec_from_file_location("layla_launcher_under_test", _LAUNCHER)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_fatal_does_not_raise_when_stderr_is_none(L, tmp_path, monkeypatch):
    monkeypatch.setenv("LAYLA_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("LAYLA_NO_DIALOG", "1")   # no MessageBox in tests
    monkeypatch.setattr(sys, "stderr", None)     # the packaged console=False reality
    # Must not raise (previously: AttributeError: 'NoneType' object has no attribute 'write')
    L._fatal("Title", "the real boot error")
    log = tmp_path / "logs" / "launch.log"
    assert log.is_file(), "the fatal message must still reach the log even with no stderr"
    assert "the real boot error" in log.read_text(encoding="utf-8")


def test_pick_python_prefers_embedded(L, tmp_path):
    (tmp_path / "python").mkdir()
    exe = tmp_path / "python" / "python.exe"
    exe.write_text("")  # just needs to exist
    assert L._pick_python(tmp_path) == exe


def test_pick_python_refuses_frozen_launcher_exe(L, tmp_path, monkeypatch):
    # Frozen build, no embedded python next to the app -> must return None (caller shows a reinstall
    # error) rather than sys.executable (== the frozen layla.exe), which would produce `layla.exe -c ...`.
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    assert L._pick_python(tmp_path) is None


def test_pick_python_uses_current_interpreter_from_source(L, tmp_path, monkeypatch):
    monkeypatch.delattr(sys, "frozen", raising=False)
    assert L._pick_python(tmp_path) == Path(sys.executable).resolve()
