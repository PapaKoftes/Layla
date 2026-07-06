"""Structured tool args validation."""
import sys
from pathlib import Path

AGENT_DIR = Path(__file__).resolve().parent.parent
if str(AGENT_DIR) not in sys.path:
    sys.path.insert(0, str(AGENT_DIR))


def test_git_commit_requires_message(monkeypatch):
    import runtime_safety

    monkeypatch.setattr(runtime_safety, "load_config", lambda: {"tool_args_validation_enabled": True})
    from services.tools.tool_args import validate_tool_args

    err = validate_tool_args("git_commit", {})
    assert err is not None
    assert "message" in (err.get("message") or "")


def test_search_codebase_requires_symbol(monkeypatch):
    import runtime_safety

    monkeypatch.setattr(runtime_safety, "load_config", lambda: {"tool_args_validation_enabled": True})
    from services.tools.tool_args import validate_tool_args

    err = validate_tool_args("search_codebase", {"root": "/tmp"})
    assert err is not None


def test_validation_disabled(monkeypatch):
    import runtime_safety

    monkeypatch.setattr(runtime_safety, "load_config", lambda: {"tool_args_validation_enabled": False})
    from services.tools.tool_args import validate_tool_args

    assert validate_tool_args("git_commit", {}) is None


# ── Tier 4: expanded dangerous-tool schema coverage ─────────────────

def _enabled(monkeypatch):
    """Helper: ensure validation is enabled."""
    import runtime_safety
    monkeypatch.setattr(runtime_safety, "load_config", lambda: {"tool_args_validation_enabled": True})


def test_write_file_requires_path_and_content(monkeypatch):
    _enabled(monkeypatch)
    from services.tools.tool_args import validate_tool_args

    assert validate_tool_args("write_file", {"path": "/x"}) is not None
    assert validate_tool_args("write_file", {"content": "x"}) is not None
    assert validate_tool_args("write_file", {"path": "/x", "content": "hi"}) is None


def test_apply_patch_requires_args(monkeypatch):
    _enabled(monkeypatch)
    from services.tools.tool_args import validate_tool_args

    assert validate_tool_args("apply_patch", {}) is not None
    assert validate_tool_args("apply_patch", {"original_path": "f.py", "patch_text": "---"}) is None


def test_run_python_requires_code_and_cwd(monkeypatch):
    _enabled(monkeypatch)
    from services.tools.tool_args import validate_tool_args

    assert validate_tool_args("run_python", {"code": "1+1"}) is not None
    assert validate_tool_args("run_python", {"code": "1+1", "cwd": "/tmp"}) is None


def test_git_push_requires_repo(monkeypatch):
    _enabled(monkeypatch)
    from services.tools.tool_args import validate_tool_args

    assert validate_tool_args("git_push", {"branch": "main"}) is not None
    assert validate_tool_args("git_push", {"repo": "/r"}) is None


def test_send_email_requires_to_subject_body(monkeypatch):
    _enabled(monkeypatch)
    from services.tools.tool_args import validate_tool_args

    assert validate_tool_args("send_email", {"to": "a@b"}) is not None
    assert validate_tool_args("send_email", {"to": "a@b", "subject": "hi", "body": "yo"}) is None


def test_click_ui_requires_coords(monkeypatch):
    _enabled(monkeypatch)
    from services.tools.tool_args import validate_tool_args

    assert validate_tool_args("click_ui", {"x": 10}) is not None
    assert validate_tool_args("click_ui", {"x": 10, "y": 20}) is None


def test_click_ui_rejects_wrong_types(monkeypatch):
    _enabled(monkeypatch)
    from services.tools.tool_args import validate_tool_args

    err = validate_tool_args("click_ui", {"x": "bad", "y": 20})
    assert err is not None


def test_docker_run_requires_image(monkeypatch):
    _enabled(monkeypatch)
    from services.tools.tool_args import validate_tool_args

    assert validate_tool_args("docker_run", {}) is not None
    assert validate_tool_args("docker_run", {"image": "alpine"}) is None


def test_replace_in_file_requires_args(monkeypatch):
    _enabled(monkeypatch)
    from services.tools.tool_args import validate_tool_args

    assert validate_tool_args("replace_in_file", {"path": "f"}) is not None
    assert validate_tool_args("replace_in_file", {"path": "f", "old_text": "a", "new_text": "b"}) is None


def test_git_clone_requires_url_and_dest(monkeypatch):
    _enabled(monkeypatch)
    from services.tools.tool_args import validate_tool_args

    assert validate_tool_args("git_clone", {"url": "https://x"}) is not None
    assert validate_tool_args("git_clone", {"url": "https://x", "dest": "/d"}) is None


def test_empty_required_string_rejected(monkeypatch):
    _enabled(monkeypatch)
    from services.tools.tool_args import validate_tool_args

    err = validate_tool_args("write_file", {"path": "  ", "content": "x"})
    assert err is not None and "empty" in err["message"]


def test_all_dangerous_tools_have_schemas():
    """Every tool marked dangerous in domain manifests must have a TOOL_SCHEMAS entry."""
    from layla.tools import registry
    from services.tools.tool_args import TOOL_SCHEMAS

    missing = []
    for name, meta in registry.TOOLS.items():
        if meta.get("dangerous") and name not in TOOL_SCHEMAS:
            missing.append(name)
    assert not missing, f"Dangerous tools without arg schemas: {missing}"


def test_schema_count_is_at_least_33():
    from services.tools.tool_args import TOOL_SCHEMAS
    assert len(TOOL_SCHEMAS) >= 33, f"Expected >= 33 schemas, got {len(TOOL_SCHEMAS)}"
