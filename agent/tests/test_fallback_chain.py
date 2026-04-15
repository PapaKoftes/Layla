from __future__ import annotations


def test_llm_gateway_uses_model_fallback_chain(monkeypatch, tmp_path):
    from services import llm_gateway
    from services.model_router import reset_router_config_cache

    reset_router_config_cache()

    default_p = tmp_path / "default.gguf"
    default_p.write_bytes(b"x")
    fb1_p = tmp_path / "fb1.gguf"
    fb1_p.write_bytes(b"x")
    missing_p = tmp_path / "missing.gguf"

    def fake_resolve(cfg):
        fn = (cfg.get("model_filename") or "").strip()
        if fn == "missing.gguf":
            return missing_p
        if fn == "fb1.gguf":
            return fb1_p
        return default_p

    def fake_cfg():
        return {
            "model_filename": "default.gguf",
            "coding_model": "missing.gguf",
            "model_fallback_chain": ["fb1.gguf"],
            "models_dir": str(tmp_path),
            "models": {},
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
        }

    monkeypatch.setattr("runtime_safety.load_config", fake_cfg)
    monkeypatch.setattr("runtime_safety.resolve_model_path", fake_resolve)

    class FakeLlama:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

    monkeypatch.setattr("llama_cpp.Llama", FakeLlama)

    llm_gateway.set_model_override("coding")
    try:
        llm_gateway._llm_by_path.clear()
        llm_gateway._llm = None
        inst = llm_gateway._get_llm()
        assert isinstance(inst, FakeLlama)
        assert str(inst.kwargs.get("model_path")) == str(fb1_p)
    finally:
        llm_gateway.set_model_override(None)

