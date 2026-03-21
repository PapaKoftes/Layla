"""Dual-model routing: is_routing_enabled, resolve_dual_model_basenames, classify_task_for_routing."""

from services.model_router import (
    classify_task,
    classify_task_for_routing,
    is_routing_enabled,
    reset_router_config_cache,
    resolve_dual_model_basenames,
)


def test_is_routing_enabled_true_when_dual_paths_set(monkeypatch):
    reset_router_config_cache()

    def _cfg():
        return {
            "model_filename": "x.gguf",
            "chat_model_path": "/some/path/chat.gguf",
            "agent_model_path": "",
            "models": {},
        }

    monkeypatch.setattr("runtime_safety.load_config", _cfg)
    reset_router_config_cache()
    assert is_routing_enabled()


def test_is_routing_enabled_force_dual_not_enough_with_single_resolvable_gguf(tmp_path, monkeypatch):
    """force_dual_models alone does not enable routing if only one GGUF resolves (no chat path/model)."""
    (tmp_path / "b.gguf").write_bytes(b"y")
    reset_router_config_cache()

    def _cfg_one_file():
        return {
            "force_dual_models": True,
            "model_filename": "b.gguf",
            "models_dir": str(tmp_path),
            "models": {},
        }

    monkeypatch.setattr("runtime_safety.load_config", _cfg_one_file)
    reset_router_config_cache()
    assert not is_routing_enabled()


def test_is_routing_enabled_true_when_chat_and_agent_files_plus_force_dual(tmp_path, monkeypatch):
    (tmp_path / "a.gguf").write_bytes(b"x")
    (tmp_path / "b.gguf").write_bytes(b"y")
    reset_router_config_cache()

    def _cfg():
        return {
            "force_dual_models": True,
            "model_filename": "b.gguf",
            "chat_model": "a.gguf",
            "models_dir": str(tmp_path),
            "models": {},
        }

    monkeypatch.setattr("runtime_safety.load_config", _cfg)
    reset_router_config_cache()
    assert is_routing_enabled()


def test_resolve_dual_model_basenames(tmp_path, monkeypatch):
    (tmp_path / "chat.gguf").write_bytes(b"c")
    (tmp_path / "agent.gguf").write_bytes(b"a")
    cfg = {
        "model_filename": "agent.gguf",
        "chat_model": "chat.gguf",
        "models_dir": str(tmp_path),
        "models": {},
    }
    monkeypatch.setattr("runtime_safety.load_config", lambda: cfg)
    ch, ag = resolve_dual_model_basenames(cfg)
    assert ch == "chat.gguf"
    assert ag == "agent.gguf"


def test_classify_task_for_routing_default_to_chat(monkeypatch):
    reset_router_config_cache()
    c = {
        "route_default_to_chat_model": True,
        "chat_model": "fast.gguf",
        "model_filename": "big.gguf",
        "models": {},
    }
    monkeypatch.setattr("runtime_safety.load_config", lambda: c)
    reset_router_config_cache()
    raw = "word " * 35
    assert classify_task(raw, "") == "default"
    assert classify_task_for_routing(raw, "", c) == "chat"


def test_classify_task_for_routing_respects_flag_off(monkeypatch):
    reset_router_config_cache()
    c = {
        "route_default_to_chat_model": False,
        "chat_model": "fast.gguf",
        "model_filename": "big.gguf",
        "models": {},
    }
    monkeypatch.setattr("runtime_safety.load_config", lambda: c)
    reset_router_config_cache()
    raw = "word " * 35
    assert classify_task_for_routing(raw, "", c) == "default"
