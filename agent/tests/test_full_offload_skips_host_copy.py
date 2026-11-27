"""A fully GPU-offloaded model is loaded without a memory-mapped host copy.

Measured (jinx-20b on an RTX 5060 Ti, 31 GB RAM): use_mmap=True kept +16.3 GB resident in host RAM (system
95%) although every layer was in VRAM; use_mmap=False: +2.2 GB (50%) and a faster load (7 s vs 12 s). The
installers write "use_mmap": true as a blanket default, so the load decides.
"""
import pytest


def _load(monkeypatch, tmp_path, *, n_gpu_layers, offload_ok, **extra):
    from services.infrastructure import auto_tune
    from services.llm import llm_gateway

    model_p = tmp_path / "m.gguf"
    model_p.write_bytes(b"x")
    cfg = {"model_filename": "m.gguf", "models_dir": str(tmp_path), "n_ctx": 512, "n_batch": 128,
           "n_gpu_layers": n_gpu_layers, "n_threads": 1, "n_threads_batch": 1, "use_mlock": True,
           "use_mmap": True, "flash_attn": False, "n_keep": 64, "speculative_decoding_enabled": False, **extra}
    monkeypatch.setattr("runtime_safety.load_config", lambda *a, **k: cfg)
    monkeypatch.setattr("runtime_safety.resolve_model_path", lambda c: model_p)
    monkeypatch.setattr(auto_tune, "_GPU_OFFLOAD", offload_ok)
    seen = {}

    class FakeLlama:
        def __init__(self, **kwargs):
            seen.update(kwargs)

    monkeypatch.setattr("llama_cpp.Llama", FakeLlama, raising=True)
    llm_gateway._llm_by_path.clear()
    llm_gateway._llm = None
    llm_gateway._get_llm()
    assert seen, "PROBE BROKEN: Llama() was never constructed"
    llm_gateway._llm_by_path.clear()
    llm_gateway._llm = None
    return seen


@pytest.fixture(autouse=True)
def _need_llama():
    pytest.importorskip("llama_cpp")


def test_full_offload_loads_without_mmap_or_mlock(monkeypatch, tmp_path):
    kw = _load(monkeypatch, tmp_path, n_gpu_layers=-1, offload_ok=True)
    assert kw["use_mmap"] is False and kw["use_mlock"] is False, kw


@pytest.mark.parametrize("layers,offload_ok", [(0, True), (20, True), (-1, False)])
def test_partial_cpu_or_no_gpu_build_keeps_the_configured_mmap(monkeypatch, tmp_path, layers, offload_ok):
    kw = _load(monkeypatch, tmp_path, n_gpu_layers=layers, offload_ok=offload_ok)
    assert kw["use_mmap"] is True and kw["use_mlock"] is True, kw


def test_operator_can_keep_the_host_copy(monkeypatch, tmp_path):
    kw = _load(monkeypatch, tmp_path, n_gpu_layers=-1, offload_ok=True, use_mmap_full_offload=True)
    assert kw["use_mmap"] is True, kw
