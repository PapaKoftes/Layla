"""audit round-5 HIGH security fixes."""
import inspect
import sys
from pathlib import Path

AGENT_DIR = Path(__file__).resolve().parent.parent
if str(AGENT_DIR) not in sys.path:
    sys.path.insert(0, str(AGENT_DIR))


def test_plugins_enabled_gate_is_remote_protected():
    # #9: a remote /settings write must not flip the plugin-code-execution consent gate (or hook gates).
    from routers.settings import _REMOTE_PROTECTED_KEYS as P
    for k in ("plugins_enabled", "agent_hooks_enabled", "hooks_require_allow_run", "skill_venv_enabled"):
        assert k in P, f"{k} (a code-exec gate) is not remote-protected"


def test_fetch_url_uses_redirect_guarded_opener():
    # #10: the default fetch path must use safe_urlopen (re-validates each redirect hop / rebinding),
    # not a raw urlopen that follows 3xx to internal hosts.
    from layla.tools import web
    src = inspect.getsource(web.fetch_url)
    assert "safe_urlopen(" in src, "fetch_url must fetch via url_guard.safe_urlopen"
    assert "urllib.request.urlopen(" not in src, "fetch_url still uses a raw, redirect-unguarded urlopen"


def test_bulk_file_tools_revalidate_each_file_against_sandbox():
    # #5/#6/#7: search_replace / rename_symbol / grep_code must re-check EACH rglob-matched file with
    # inside_sandbox (root-only check let an in-sandbox symlink be read/written through to outside).
    import inspect
    from layla.tools.impl import code, file_ops
    for fn in (file_ops.search_replace, code.rename_symbol):
        src = inspect.getsource(fn)
        loop = src.split("rglob(", 1)[1]
        assert "inside_sandbox(f)" in loop, f"{fn.__name__} does not re-validate each matched file"
    gsrc = inspect.getsource(code.grep_code)
    assert "inside_sandbox(f)" in gsrc, "grep_code does not re-validate each matched file"


def test_search_replace_does_not_write_through_symlink(tmp_path):
    # Behavioral (Linux / privileged Windows): a symlink inside the sandbox pointing OUTSIDE must not be
    # written through. Skips where symlink creation isn't permitted.
    import os
    import pytest
    from unittest.mock import patch
    from layla.tools import sandbox_core

    sandbox = tmp_path / "sandbox"; sandbox.mkdir()
    outside = tmp_path / "outside_secret.txt"; outside.write_text("ORIGINAL SECRET", encoding="utf-8")
    link = sandbox / "evil.txt"
    try:
        os.symlink(outside, link)
    except (OSError, NotImplementedError):
        pytest.skip("symlink creation not permitted in this environment")

    from layla.tools.impl import file_ops
    with patch.multiple(sandbox_core, _get_sandbox=lambda: sandbox.resolve()), \
         patch.object(file_ops._effective_sandbox, "path", str(sandbox.resolve()), create=True):
        file_ops.search_replace(root=str(sandbox), find="ORIGINAL", replace="PWNED",
                                file_glob="evil.txt", dry_run=False)
    # The out-of-sandbox target must be untouched.
    assert outside.read_text(encoding="utf-8") == "ORIGINAL SECRET"


def test_executor_clamps_workspace_outside_config_sandbox_root(tmp_path):
    # #1: a caller-supplied workspace (sandbox_root arg) that resolves OUTSIDE config sandbox_root must be
    # clamped to config sandbox_root before it becomes the thread-local effective sandbox — else generic
    # write tools escape. A subdir of sandbox_root is fine.
    from unittest.mock import patch
    import core.executor as ex
    import layla.tools.registry as reg

    cfg_root = tmp_path / "safe"; cfg_root.mkdir()
    outside = tmp_path / "evil"; outside.mkdir()
    subdir = cfg_root / "sub"; subdir.mkdir()

    def _run(sbx):
        # The executor calls set_effective_sandbox twice: the setup call (the effective sandbox) then a
        # teardown reset to None — capture the SETUP (first non-None) call.
        calls = []
        with patch.dict(reg.TOOLS, {"noop": {"fn": lambda **k: {"ok": True}}}, clear=False), \
             patch.object(reg, "set_effective_sandbox", lambda ws: calls.append(ws)), \
             patch("runtime_safety.load_config", lambda: {"sandbox_root": str(cfg_root)}):
            ex.run_tool("noop", {}, sandbox_root=str(sbx))
        non_none = [c for c in calls if c]
        return non_none[0] if non_none else None

    assert _run(outside) == str(cfg_root)          # outside → clamped to config root
    assert _run(subdir) == str(subdir)             # subdir of sandbox_root → preserved
    assert _run(cfg_root) == str(cfg_root)         # exact root → preserved
