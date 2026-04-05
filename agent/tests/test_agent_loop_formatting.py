"""Regression tests for extracted agent loop helpers."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

AGENT_DIR = Path(__file__).resolve().parent.parent
if str(AGENT_DIR) not in sys.path:
    sys.path.insert(0, str(AGENT_DIR))

from services.agent_loop_formatting import format_tool_steps_for_prompt  # noqa: E402
from services.context_window_ux import emit_context_window_ux  # noqa: E402


def test_format_tool_steps_for_prompt_empty():
    assert format_tool_steps_for_prompt([]) == ""


def test_format_tool_steps_for_prompt_dict_result():
    s = format_tool_steps_for_prompt(
        [{"action": "read_file", "result": {"ok": True, "content": "hello"}}]
    )
    assert "read_file" in s
    assert "hello" in s


def test_emit_context_window_ux_no_queue_noop():
    emit_context_window_ux(
        None,
        [],
        {"n_ctx": 4096},
        {"original_goal": "x", "steps": []},
        format_steps=format_tool_steps_for_prompt,
    )
