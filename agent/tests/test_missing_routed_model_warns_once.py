"""A routed model that isn't installed is reported once per process, not on every turn.

Live: with models.code set to an undownloaded Magicoder, each turn logged the same "not found" warning ~4
times (100+ lines per short session), burying every real warning in the server log.
"""
import logging
import sys
from pathlib import Path

AGENT_DIR = Path(__file__).resolve().parent.parent
if str(AGENT_DIR) not in sys.path:
    sys.path.insert(0, str(AGENT_DIR))


def test_router_warns_once_per_missing_model(monkeypatch, tmp_path, caplog):
    import runtime_safety
    from services.llm import model_router as mr

    monkeypatch.setattr(runtime_safety, "load_config", lambda *a, **k: {"model_filename": "main.gguf"})
    monkeypatch.setattr(runtime_safety, "resolve_model_path", lambda cfg: tmp_path / cfg["model_filename"])
    monkeypatch.setattr(mr, "_WARNED_MISSING", set())

    with caplog.at_level(logging.WARNING, logger="layla"):
        for _ in range(5):
            mr._warn_router_model_missing("missing-coder.gguf", "route_model")
        mr._warn_router_model_missing("other-missing.gguf", "route_model")
    msgs = [r.getMessage() for r in caplog.records if "model_router fallback" in r.getMessage()]
    assert len(msgs) == 2, msgs
    assert "missing-coder.gguf" in msgs[0] and "other-missing.gguf" in msgs[1]


def test_gateway_fallback_warning_is_deduplicated_in_source():
    """Both gateway branches route through the once-per-process set (AST: each logger call is preceded by
    a membership test on _ROUTED_MISSING_WARNED)."""
    src = (AGENT_DIR / "services" / "llm" / "llm_gateway.py").read_text(encoding="utf-8")
    assert src.count("_log = logger.debug if wanted in _ROUTED_MISSING_WARNED else logger.warning") == 2
    assert "routed model missing" in src, "PROBE BROKEN: gateway message changed"
