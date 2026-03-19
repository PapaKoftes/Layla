"""Structured tool args validation."""
import sys
from pathlib import Path

AGENT_DIR = Path(__file__).resolve().parent.parent
if str(AGENT_DIR) not in sys.path:
    sys.path.insert(0, str(AGENT_DIR))


def test_git_commit_requires_message(monkeypatch):
    import runtime_safety

    monkeypatch.setattr(runtime_safety, "load_config", lambda: {"tool_args_validation_enabled": True})
    from services.tool_args import validate_tool_args

    err = validate_tool_args("git_commit", {})
    assert err is not None
    assert "message" in (err.get("message") or "")


def test_search_codebase_requires_symbol(monkeypatch):
    import runtime_safety

    monkeypatch.setattr(runtime_safety, "load_config", lambda: {"tool_args_validation_enabled": True})
    from services.tool_args import validate_tool_args

    err = validate_tool_args("search_codebase", {"root": "/tmp"})
    assert err is not None


def test_validation_disabled(monkeypatch):
    import runtime_safety

    monkeypatch.setattr(runtime_safety, "load_config", lambda: {"tool_args_validation_enabled": False})
    from services.tool_args import validate_tool_args

    assert validate_tool_args("git_commit", {}) is None
