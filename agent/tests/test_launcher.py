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


# ── Installed builds keep models under the per-user data dir (found by the clean-VM install gate) ────
def _example(tmp_path, body: str) -> Path:
    root = tmp_path / "install"
    (root / "agent").mkdir(parents=True)
    ex = root / "agent" / "runtime_config.example.json"
    ex.write_text(body, encoding="utf-8")
    return root


def test_seed_drops_pinned_models_dir_so_the_data_dir_default_owns_it(L, tmp_path):
    root = _example(tmp_path, '{"models_dir": "~/.layla/models", "model_filename": "your-model.gguf", "n_ctx": 4096}')
    data = tmp_path / "data"
    data.mkdir()
    L._seed_runtime_config(root, data)
    import json
    seeded = json.loads((data / "runtime_config.json").read_text(encoding="utf-8"))
    assert "models_dir" not in seeded, "a pinned ~/.layla/models sends installed-build models outside the data dir"
    assert seeded["model_filename"] == "your-model.gguf" and seeded["n_ctx"] == 4096, "other keys must survive"


def test_seed_never_touches_an_existing_config(L, tmp_path):
    root = _example(tmp_path, '{"models_dir": "~/.layla/models"}')
    data = tmp_path / "data"
    data.mkdir()
    existing = '{"models_dir": "D:/my-models", "model_filename": "mine.gguf"}'
    (data / "runtime_config.json").write_text(existing, encoding="utf-8")
    L._seed_runtime_config(root, data)
    assert (data / "runtime_config.json").read_text(encoding="utf-8") == existing


def test_seed_accepts_a_bom_example(L, tmp_path):
    root = _example(tmp_path, '\ufeff{"models_dir": "~/.layla/models", "model_filename": "x.gguf"}')
    data = tmp_path / "data"
    data.mkdir()
    L._seed_runtime_config(root, data)
    import json
    seeded = json.loads((data / "runtime_config.json").read_text(encoding="utf-8"))
    assert "models_dir" not in seeded and seeded["model_filename"] == "x.gguf"


def test_shipped_example_really_pins_models_dir():
    """PROBE: the seed fix only matters while the shipped example pins models_dir. If someone removes it
    from the example, this goes red so the seed special-case can be deleted rather than rot."""
    import json
    ex = Path(__file__).resolve().parents[1] / "runtime_config.example.json"
    assert "models_dir" in json.loads(ex.read_text(encoding="utf-8-sig"))
