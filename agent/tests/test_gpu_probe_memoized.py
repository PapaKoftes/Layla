"""The native GPU-offload probe runs at most once per process.

load_config re-applies auto-tune whenever its cache expires, and each pass called
llama_cpp.llama_supports_gpu_offload(). Its first call loads every llama.cpp backend library; on
GitHub's Windows runners that sometimes ran past the 120s per-test timeout (4 of 6 nightly master runs
failed in load_config -> apply_auto_tune -> _gpu_offload_available).
"""
import sys
import types
from pathlib import Path

AGENT_DIR = Path(__file__).resolve().parent.parent
if str(AGENT_DIR) not in sys.path:
    sys.path.insert(0, str(AGENT_DIR))


def test_probe_runs_once_and_caches_the_answer(monkeypatch):
    from services.infrastructure import auto_tune

    calls = []
    fake = types.SimpleNamespace(llama_supports_gpu_offload=lambda: calls.append(1) or True)
    monkeypatch.setitem(sys.modules, "llama_cpp", fake)
    monkeypatch.setattr(auto_tune, "_GPU_OFFLOAD", None)

    assert auto_tune._gpu_offload_available() is True
    assert auto_tune._gpu_offload_available() is True
    assert calls == [1], f"native probe ran {len(calls)} times"


def test_a_failing_probe_is_treated_as_no_offload(monkeypatch):
    from services.infrastructure import auto_tune

    def boom():
        raise OSError("backend load failed")

    monkeypatch.setitem(sys.modules, "llama_cpp", types.SimpleNamespace(llama_supports_gpu_offload=boom))
    monkeypatch.setattr(auto_tune, "_GPU_OFFLOAD", None)
    assert auto_tune._gpu_offload_available() is False


def test_unit_tests_never_reach_the_native_probe():
    from services.infrastructure import auto_tune

    assert auto_tune._GPU_OFFLOAD is False, "conftest's _no_native_gpu_probe did not pin the probe"
