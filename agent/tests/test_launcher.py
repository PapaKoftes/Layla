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


def test_resolve_agent_dir_prefers_override(L, tmp_path):
    install = tmp_path / "install"; (install / "agent").mkdir(parents=True); (install / "agent" / "main.py").write_text("")
    data = tmp_path / "data"
    # No override yet -> shipped copy.
    assert L._resolve_agent_dir(install, data) == install / "agent"
    # Override with a main.py -> preferred (this is how a no-admin update takes effect).
    ov = data / "app_override" / "agent"; ov.mkdir(parents=True); (ov / "main.py").write_text("")
    assert L._resolve_agent_dir(install, data) == ov


# ── thin bootstrapper (layla_boot.py) ─────────────────────────────────────────
_BOOT = Path(__file__).resolve().parents[2] / "launcher" / "layla_boot.py"


@pytest.fixture()
def B():
    spec = importlib.util.spec_from_file_location("layla_boot_under_test", _BOOT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_boot_resolves_launcher_override_first(B, tmp_path):
    install = tmp_path / "install"; (install / "launcher").mkdir(parents=True)
    (install / "launcher" / "layla_launcher.py").write_text("# shipped")
    data = tmp_path / "data"
    assert B._resolve_launcher(install, data) == install / "launcher" / "layla_launcher.py"
    ov = data / "app_override" / "launcher"; ov.mkdir(parents=True)
    (ov / "layla_launcher.py").write_text("# updated")
    assert B._resolve_launcher(install, data) == ov / "layla_launcher.py"


def test_boot_missing_launcher_is_none(B, tmp_path):
    assert B._resolve_launcher(tmp_path / "install", tmp_path / "data") is None


def test_boot_python_refuses_frozen(B, tmp_path, monkeypatch):
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    assert B._resolve_python(tmp_path) is None
