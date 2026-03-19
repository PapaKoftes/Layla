"""Tests for task classification, model routing, llm_model_coding capability, performance_mode."""

from capabilities.registry import CAPABILITIES, CapabilityImpl


def test_classify_task_coding_keywords():
    from services.model_router import classify_task

    assert classify_task("fix the bug in my function") == "coding"
    assert classify_task("implement a REST handler") == "coding"


def test_classify_task_reasoning_keywords():
    from services.model_router import classify_task

    assert classify_task("explain why this algorithm works") == "reasoning"
    assert classify_task("analyze the tradeoffs") == "reasoning"


def test_classify_task_default_chat():
    from services.model_router import classify_task

    assert classify_task("hello") == "chat"


def test_route_model_returns_none_when_unset(monkeypatch):
    from services.model_router import reset_router_config_cache, route_model

    reset_router_config_cache()

    def _empty_cfg():
        return {}

    monkeypatch.setattr("runtime_safety.load_config", _empty_cfg)
    reset_router_config_cache()
    assert route_model("coding") is None
    assert route_model("reasoning") is None


def test_capability_registry_llm_model_coding_exists():
    assert "llm_model_coding" in CAPABILITIES
    assert any(i.id == "magicoder" for i in CAPABILITIES["llm_model_coding"])


def test_magicoder_impl_id():
    impls = CAPABILITIES.get("llm_model_coding", [])
    magic = next((i for i in impls if i.id == "magicoder"), None)
    assert magic is not None
    assert isinstance(magic, CapabilityImpl)
    assert magic.module_path == "llama_cpp"


def test_select_model_fallback_to_route(monkeypatch):
    from services.model_router import reset_router_config_cache, select_model

    reset_router_config_cache()

    def _noop_best(*_a, **_k):
        return None

    monkeypatch.setattr("capabilities.registry.get_active_implementation", _noop_best)

    def _cfg():
        return {
            "model_filename": "base.gguf",
            "coding_model": "code.gguf",
            "models": {},
        }

    monkeypatch.setattr("runtime_safety.load_config", _cfg)
    monkeypatch.setattr(
        "services.telemetry.get_user_profile",
        lambda: {"simple_ratio": 0.0, "coding_ratio": 0.0},
    )
    reset_router_config_cache()
    out = select_model("coding", 100, {}, 999999)
    assert out == "code.gguf"


def test_routing_consistency():
    """Same input always produces same model classification."""
    from services.model_router import classify_task

    for _ in range(5):
        assert classify_task("fix the bug in my function") == "coding"
        assert classify_task("explain why this works") == "reasoning"
        assert classify_task("hello") == "chat"


def test_missing_model_graceful_fallback(monkeypatch, tmp_path):
    """_get_llm loads default model_filename when task-routed GGUF path is missing."""
    from services import llm_gateway
    from services.model_router import reset_router_config_cache

    reset_router_config_cache()

    default_p = tmp_path / "default.gguf"
    default_p.write_bytes(b"x")
    missing_p = tmp_path / "missing.gguf"
    resolved_order: list[str] = []

    def fake_resolve(cfg):
        fn = (cfg.get("model_filename") or "").strip()
        resolved_order.append(fn)
        if fn == "missing.gguf":
            return missing_p
        return default_p

    def fake_cfg():
        return {
            "model_filename": "default.gguf",
            "coding_model": "missing.gguf",
            "models_dir": str(tmp_path),
            "models": {},
            "n_ctx": 512,
            "n_batch": 512,
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
    reset_router_config_cache()

    class FakeLlama:
        def __init__(self, **kwargs):
            self.kwargs = kwargs
            mp = str(kwargs.get("model_path", ""))
            assert not mp.endswith("missing.gguf")

    monkeypatch.setattr("llama_cpp.Llama", FakeLlama)

    llm_gateway.set_model_override("coding")
    try:
        llm_gateway._llm_by_path.clear()
        llm_gateway._llm = None
        inst = llm_gateway._get_llm()
        assert isinstance(inst, FakeLlama)
        assert str(inst.kwargs.get("model_path")) == str(default_p)
        assert "missing.gguf" in resolved_order
        assert "default.gguf" in resolved_order
    finally:
        llm_gateway.set_model_override(None)


def test_performance_mode_low_reduces_ctx():
    from services.system_optimizer import get_effective_config

    eff = get_effective_config({
        "n_ctx": 8192,
        "max_tool_calls": 10,
        "research_max_tool_calls": 40,
        "semantic_k": 8,
        "knowledge_chunks_k": 8,
        "knowledge_max_bytes": 8000,
        "performance_mode": "low",
        "max_plan_depth": 3,
        "planning_enabled": True,
    })
    assert eff["n_ctx"] <= 2048
    assert eff["max_tool_calls"] <= 3
    assert eff.get("retrieval_cross_encoder_limit") == 0
