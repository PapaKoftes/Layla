from __future__ import annotations


def test_speculative_decoding_injects_draft_model(monkeypatch, tmp_path):
    """
    When speculative_decoding_enabled is true, llm_gateway._get_llm should pass
    a draft_model kwarg (best-effort; may be ignored by older llama-cpp-python).
    """
    from services import llm_gateway

    model_p = tmp_path / "m.gguf"
    model_p.write_bytes(b"x")

    def fake_cfg():
        return {
            "model_filename": "m.gguf",
            "models_dir": str(tmp_path),
            "n_ctx": 512,
            "n_batch": 128,
            "n_gpu_layers": 0,
            "n_threads": 1,
            "n_threads_batch": 1,
            "use_mlock": False,
            "use_mmap": True,
            "flash_attn": False,
            "type_k": 8,
            "type_v": 8,
            "n_keep": 64,
            "speculative_decoding_enabled": True,
            "speculative_num_pred_tokens": 5,
        }

    monkeypatch.setattr("runtime_safety.load_config", fake_cfg)
    monkeypatch.setattr("runtime_safety.resolve_model_path", lambda cfg: model_p)

    # Provide a minimal speculative class so the import succeeds without depending on llama_cpp extras.
    class FakePromptLookup:
        def __init__(self, num_pred_tokens: int = 10):
            self.num_pred_tokens = num_pred_tokens

    monkeypatch.setattr(
        "llama_cpp.llama_speculative.LlamaPromptLookupDecoding",
        FakePromptLookup,
        raising=False,
    )

    seen = {}

    class FakeLlama:
        def __init__(self, **kwargs):
            seen.update(kwargs)

    monkeypatch.setattr("llama_cpp.Llama", FakeLlama, raising=True)

    llm_gateway._llm_by_path.clear()
    llm_gateway._llm = None
    inst = llm_gateway._get_llm()
    assert isinstance(inst, FakeLlama)
    assert "draft_model" in seen
    assert getattr(seen["draft_model"], "num_pred_tokens", None) == 5


def test_speculative_decoding_disabled(monkeypatch, tmp_path):
    from services import llm_gateway

    model_p = tmp_path / "m.gguf"
    model_p.write_bytes(b"x")

    def fake_cfg():
        return {
            "model_filename": "m.gguf",
            "models_dir": str(tmp_path),
            "n_ctx": 512,
            "n_batch": 128,
            "n_gpu_layers": 0,
            "n_threads": 1,
            "n_threads_batch": 1,
            "use_mlock": False,
            "use_mmap": True,
            "flash_attn": False,
            "type_k": 8,
            "type_v": 8,
            "n_keep": 64,
            "speculative_decoding_enabled": False,
        }

    monkeypatch.setattr("runtime_safety.load_config", fake_cfg)
    monkeypatch.setattr("runtime_safety.resolve_model_path", lambda cfg: model_p)

    seen = {}

    class FakeLlama:
        def __init__(self, **kwargs):
            seen.update(kwargs)

    monkeypatch.setattr("llama_cpp.Llama", FakeLlama, raising=True)

    llm_gateway._llm_by_path.clear()
    llm_gateway._llm = None
    llm_gateway._get_llm()
    assert "draft_model" not in seen

