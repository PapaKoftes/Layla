"""
Tests for unified intent router.
"""
import sys
from pathlib import Path

AGENT_DIR = Path(__file__).resolve().parent.parent
if str(AGENT_DIR) not in sys.path:
    sys.path.insert(0, str(AGENT_DIR))


def test_route_intent_meta_self_defaults_to_chat():
    from services.intent_router import route_intent

    rd = route_intent("please explain your full capabilities", context="", workspace_root="")
    assert rd.task_type == "chat"
    assert rd.is_meta_self is True
    assert rd.has_workspace_signals is False


def test_route_intent_traceback_is_workspace_signal():
    from services.intent_router import route_intent

    rd = route_intent("please explain this traceback in foo.py line 12", context="", workspace_root="")
    assert rd.has_workspace_signals is True
    assert rd.task_type in ("reasoning", "coding", "default")


def test_route_intent_mixed_sets_multi_intent():
    from services.intent_router import route_intent

    rd = route_intent("explain your capabilities and read agent/agent_loop.py", context="", workspace_root="")
    assert rd.multi_intent is True
