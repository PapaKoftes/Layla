"""BL-159: ONNX Runtime GenAI backend — detection + graceful degradation."""
from __future__ import annotations

import sys
import types

from services.llm import inference_router as ir


def test_detect_onnx_when_model_path_set():
    assert ir._detect_backend({"onnx_model_path": "/models/phi3-onnx"}) == "onnx"


def test_detect_onnx_explicit():
    assert ir._detect_backend({"inference_backend": "onnx"}) == "onnx"


def test_onnx_is_a_known_backend():
    assert "onnx" in ir._BACKENDS


def test_onnx_missing_model_path():
    r = ir.run_completion_onnx({"onnx_model_path": ""}, "hi", 32, 0.0, None, False, 60)
    assert r["error"].startswith("onnx_model_path not found")
    assert r["choices"][0]["finish_reason"] == "error"


def test_onnx_missing_library(tmp_path, monkeypatch):
    # model dir exists but onnxruntime_genai is not importable
    monkeypatch.setitem(sys.modules, "onnxruntime_genai", None)
    r = ir.run_completion_onnx({"onnx_model_path": str(tmp_path)}, "hi", 32, 0.0, None, False, 60)
    assert "onnxruntime-genai not installed" in r["error"]


def test_onnx_happy_path(tmp_path, monkeypatch):
    # stub onnxruntime_genai to exercise the real code path
    og = types.ModuleType("onnxruntime_genai")

    class Model:
        def __init__(self, d): self.d = d
        def generate(self, params): return [[1, 2, 3]]

    class Tokenizer:
        def __init__(self, m): pass
        def encode(self, p): return [0]
        def decode(self, toks): return "hi there END tail"

    class GeneratorParams:
        def __init__(self, m): self.input_ids = None
        def set_search_options(self, **kw): self.opts = kw

    og.Model, og.Tokenizer, og.GeneratorParams = Model, Tokenizer, GeneratorParams
    monkeypatch.setitem(sys.modules, "onnxruntime_genai", og)
    ir._onnx_cache.clear()

    r = ir.run_completion_onnx({"onnx_model_path": str(tmp_path)}, "prompt", 16, 0.7, ["END"], False, 60)
    assert r["backend"] == "onnx"
    assert r["choices"][0]["message"]["content"] == "hi there"   # truncated at stop "END"
    assert r["choices"][0]["finish_reason"] == "stop"


def test_run_completion_routes_to_onnx(tmp_path, monkeypatch):
    called = {}

    def _fake_onnx(*a, **k):
        called["hit"] = True
        return {"choices": [], "backend": "onnx"}

    monkeypatch.setattr(ir, "run_completion_onnx", _fake_onnx)
    monkeypatch.setattr("runtime_safety.load_config", lambda: {"onnx_model_path": str(tmp_path)}, raising=False)
    out = ir.run_completion("hello", cfg_override={"onnx_model_path": str(tmp_path)})
    assert called.get("hit") and out["backend"] == "onnx"
