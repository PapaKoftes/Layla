"""R3: config_cache is a single source of truth — it delegates to runtime_safety.load_config()
(runtime_config.json), not a separate services/config.json that doesn't exist."""
import sys
from pathlib import Path

AGENT_DIR = Path(__file__).resolve().parent.parent
if str(AGENT_DIR) not in sys.path:
    sys.path.insert(0, str(AGENT_DIR))


def test_config_cache_delegates_to_runtime_safety(monkeypatch):
    import runtime_safety as rs
    from services.infrastructure import config_cache as cc
    sentinel = {"model_filename": "x.gguf", "n_ctx": 2048}
    monkeypatch.setattr(rs, "load_config", lambda: sentinel)
    assert cc.get_config() == sentinel
    assert cc.get("model_filename") == "x.gguf"
    assert cc.get("missing", "default") == "default"


def test_config_cache_matches_runtime_safety_live():
    import runtime_safety as rs
    from services.infrastructure import config_cache as cc
    assert cc.get_config() == rs.load_config()  # one source, no drift


if __name__ == "__main__":
    import pytest
    sys.exit(pytest.main([__file__, "-v"]))
