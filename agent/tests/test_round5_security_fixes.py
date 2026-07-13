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
