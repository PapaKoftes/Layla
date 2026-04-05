"""Linux cgroup v2 helper (mocked paths; no real cgroup mount required)."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

AGENT_DIR = Path(__file__).resolve().parent.parent
if str(AGENT_DIR) not in sys.path:
    sys.path.insert(0, str(AGENT_DIR))


def test_maybe_attach_skips_non_linux(monkeypatch):
    import services.worker_cgroup_linux as wcl

    monkeypatch.setattr(wcl.sys, "platform", "win32")
    proc = MagicMock()
    proc.pid = 1
    assert wcl.maybe_attach_worker_to_cgroup(proc, {"background_worker_cgroup_auto_enabled": True}) is None


def test_maybe_attach_skips_when_disabled():
    import services.worker_cgroup_linux as wcl

    proc = MagicMock()
    proc.pid = 1
    assert wcl.maybe_attach_worker_to_cgroup(proc, {"background_worker_cgroup_auto_enabled": False}) is None


def test_maybe_attach_skips_without_limits():
    import services.worker_cgroup_linux as wcl

    proc = MagicMock()
    proc.pid = 1
    cfg = {
        "background_worker_cgroup_auto_enabled": True,
        "background_worker_cgroup_memory_max_bytes": 0,
        "background_worker_cgroup_cpu_max": "",
    }
    assert wcl.maybe_attach_worker_to_cgroup(proc, cfg) is None


def test_maybe_attach_writes_procs_and_memory_max(monkeypatch, tmp_path):
    import services.worker_cgroup_linux as wcl

    monkeypatch.setattr(wcl.sys, "platform", "linux")
    root = tmp_path / "cgroup"
    root.mkdir()
    (root / "cgroup.controllers").write_text("memory cpu\n", encoding="utf-8")
    parent_rel = "user.slice"
    (root / parent_rel).mkdir(parents=True)
    monkeypatch.setattr(wcl, "CGROUP2_ROOT", root)
    monkeypatch.setattr(wcl, "_read_own_cgroup_v2_relative_path", lambda: parent_rel)

    class _Proc:
        pid = 999001

    cfg = {
        "background_worker_cgroup_auto_enabled": True,
        "background_worker_cgroup_memory_max_bytes": 4096,
        "background_worker_cgroup_cpu_max": "",
    }
    rel = wcl.maybe_attach_worker_to_cgroup(_Proc(), cfg)
    assert rel
    leaf = root / rel
    assert leaf.is_dir()
    assert (leaf / "cgroup.procs").read_text(encoding="utf-8").strip() == "999001"
    assert (leaf / "memory.max").read_text(encoding="utf-8").strip() == "4096"


def test_read_own_cgroup_v2_relative_path_parses_unified_line(monkeypatch, tmp_path):
    import pathlib

    import services.worker_cgroup_linux as wcl

    monkeypatch.setattr(wcl.sys, "platform", "linux")
    fake_proc = tmp_path / "cgroup"
    fake_proc.write_text("0::/foo/bar.scope\n", encoding="utf-8")
    _orig_read = pathlib.Path.read_text

    def _read(self, *a, **kw):
        key = str(self).replace("\\", "/")
        if key.endswith("/proc/self/cgroup") or key == "/proc/self/cgroup":
            return fake_proc.read_text(encoding="utf-8", errors="replace")
        return _orig_read(self, *a, **kw)

    monkeypatch.setattr(pathlib.Path, "read_text", _read)
    assert wcl._read_own_cgroup_v2_relative_path() == "foo/bar.scope"


def test_maybe_attach_skips_without_v2_controllers_file(monkeypatch, tmp_path):
    import services.worker_cgroup_linux as wcl

    monkeypatch.setattr(wcl.sys, "platform", "linux")
    root = tmp_path / "cgroup"
    root.mkdir()
    parent_rel = "slice"
    (root / parent_rel).mkdir()
    monkeypatch.setattr(wcl, "CGROUP2_ROOT", root)
    monkeypatch.setattr(wcl, "_read_own_cgroup_v2_relative_path", lambda: parent_rel)
    proc = MagicMock()
    proc.pid = 2
    cfg = {
        "background_worker_cgroup_auto_enabled": True,
        "background_worker_cgroup_memory_max_bytes": 100,
        "background_worker_cgroup_cpu_max": "",
    }
    assert wcl.maybe_attach_worker_to_cgroup(proc, cfg) is None


def test_maybe_attach_skips_when_parent_not_writable(monkeypatch, tmp_path):
    import services.worker_cgroup_linux as wcl

    monkeypatch.setattr(wcl.sys, "platform", "linux")
    root = tmp_path / "cgroup"
    root.mkdir()
    (root / "cgroup.controllers").write_text("", encoding="utf-8")
    parent_rel = "ro.slice"
    (root / parent_rel).mkdir()
    monkeypatch.setattr(wcl, "CGROUP2_ROOT", root)
    monkeypatch.setattr(wcl, "_read_own_cgroup_v2_relative_path", lambda: parent_rel)
    monkeypatch.setattr(wcl.os, "access", lambda *_a, **_k: False)
    proc = MagicMock()
    proc.pid = 3
    cfg = {
        "background_worker_cgroup_auto_enabled": True,
        "background_worker_cgroup_memory_max_bytes": 100,
        "background_worker_cgroup_cpu_max": "",
    }
    assert wcl.maybe_attach_worker_to_cgroup(proc, cfg) is None


@pytest.mark.skipif(sys.platform != "linux", reason="tmp_path leaf still contains cgroup.procs file; POSIX rmdir differs on Windows")
def test_maybe_remove_worker_cgroup_rmdirs_empty_leaf(monkeypatch, tmp_path):
    import services.worker_cgroup_linux as wcl

    monkeypatch.setattr(wcl.sys, "platform", "linux")
    root = tmp_path / "cgroup"
    root.mkdir()
    rel = "a/layla-bg-test"
    leaf = root / rel
    leaf.mkdir(parents=True)
    (leaf / "cgroup.procs").write_text("", encoding="utf-8")
    monkeypatch.setattr(wcl, "CGROUP2_ROOT", root)
    wcl.maybe_remove_worker_cgroup(rel)
    assert not leaf.exists()


def test_maybe_remove_rejects_path_traversal(monkeypatch, tmp_path):
    import services.worker_cgroup_linux as wcl

    monkeypatch.setattr(wcl.sys, "platform", "linux")
    root = tmp_path / "cgroup"
    root.mkdir()
    monkeypatch.setattr(wcl, "CGROUP2_ROOT", root)
    evil = tmp_path / "evil"
    evil.mkdir()
    wcl.maybe_remove_worker_cgroup("../../../evil")
    assert evil.exists()
