"""
Tests for intent-based tool category detection.
"""
import sys
from pathlib import Path

AGENT_DIR = Path(__file__).resolve().parent.parent
if str(AGENT_DIR) not in sys.path:
    sys.path.insert(0, str(AGENT_DIR))


def test_detect_intent_explain_capabilities_is_conservative():
    from services.intent_detection import _DEFAULT_CATEGORIES, detect_intent

    cats = detect_intent("please explain your full capabilities")
    assert cats == _DEFAULT_CATEGORIES


def test_detect_intent_explain_traceback_is_toolable():
    from services.intent_detection import detect_intent

    cats = detect_intent("please explain this traceback in foo.py line 12")
    assert "analysis" in cats
    assert "code" in cats
    assert "filesystem" in cats
    assert "memory" in cats
