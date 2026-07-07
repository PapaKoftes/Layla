"""Greetings must hit the deterministic fast-path (0 LLM calls, no model cold-load).

This is the fix for the "typed hello, waited ~100s, no output" report: a bare greeting
should never spin up the model. Real requests must still go to the full agent path.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

AGENT_DIR = Path(__file__).resolve().parent.parent
if str(AGENT_DIR) not in sys.path:
    sys.path.insert(0, str(AGENT_DIR))

from services.agent.response_builder import quick_reply_for_trivial_turn


@pytest.mark.parametrize(
    "greeting",
    ["hi", "Hi", "hey", "heyyy", "hello", "helloooo", "yo", "sup", "howdy",
     "hiya", "hey there", "good morning", "Good Evening", "hello!", "hey."],
)
def test_greetings_get_instant_reply(greeting):
    reply = quick_reply_for_trivial_turn(greeting)
    assert reply and reply.strip(), f"{greeting!r} should get an instant reply (no model call)"


@pytest.mark.parametrize(
    "msg",
    ["fix the auth bug", "explain how tail recursion works",
     "hello world program in rust", "why is my test failing",
     "hi, can you refactor this function", "hey what does this regex do"],
)
def test_real_requests_do_not_shortcut(msg):
    # A substantive request must NOT be short-circuited by the deterministic fast-path.
    assert quick_reply_for_trivial_turn(msg) == "", f"{msg!r} must go to the full agent path"


def test_existing_trivial_replies_still_work():
    assert quick_reply_for_trivial_turn("ok") == "Got it."
    assert quick_reply_for_trivial_turn("how are you") == "I'm good. What do you need?"
    assert quick_reply_for_trivial_turn("") == ""
