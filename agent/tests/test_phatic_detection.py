"""Content-based phatic / retrieval-skip heuristics (not length-based)."""
from __future__ import annotations

import sys
from pathlib import Path

AGENT_DIR = Path(__file__).resolve().parent.parent
if str(AGENT_DIR) not in sys.path:
    sys.path.insert(0, str(AGENT_DIR))

from agent_loop import _is_lightweight_chat_turn  # noqa: E402


def test_who_are_you_is_not_lightweight():
    assert _is_lightweight_chat_turn("who are you", "light") is False
    assert _is_lightweight_chat_turn("who are u", "light") is False


def test_questions_not_lightweight():
    assert _is_lightweight_chat_turn("what is python", "light") is False
    assert _is_lightweight_chat_turn("explain gravity", "light") is False


def test_phatic_ack_lightweight():
    assert _is_lightweight_chat_turn("thanks!", "light") is True
    assert _is_lightweight_chat_turn("ok", "light") is True
    assert _is_lightweight_chat_turn("hey", "light") is True


def test_deep_reasoning_mode_never_lightweight():
    assert _is_lightweight_chat_turn("ok", "deep") is False
