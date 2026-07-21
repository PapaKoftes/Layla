"""Layla must be able to see her own previous replies.

`convo_turns` shipped at 0. Both prompt builders gate on `if convo_turns > 0`, so the
"Recent conversation" block was never appended — on any turn, ever. `conversation_summaries`
has 0 rows, so the session-summary path was empty too. The entire visible past was a single
"Last user message:" line capped at 500 chars, and continuity was an illusion produced by
semantic recall over a 300-token memory budget. Ask "what did I just rename it to?" and the
answer was not in the prompt.

WHY 0 WAS ONCE DEFENSIBLE, AND IS NOT NOW. Every turn used to re-prefill the entire prompt
(the KV reset removed in P13-A1), so history was pure added latency. With prefix reuse working
it is cheap. MEASURED on this box — marginal prefill on the non-reused tail is 155 tok/s, and
stream_handler gives the last 2 messages 600 chars and older ones 220:

    convo_turns  2 -> ~300 tok -> 1.9s      6 -> ~520 tok -> 3.3s
                 8 -> ~630 tok -> 4.1s     12 -> ~850 tok -> 5.5s and OVERFLOWS the window

6 costs ~3.3s on top of a ~0.6s first token, still ~5.8x faster than the 22.6s every
no-history turn cost before A1. The ceiling is the context window, not the clock: head ~860 +
reply reserve 320 + history must fit 2048, so 12 lands at ~2060 and 10 is the safe maximum.

These tests pin the CONTRACT — that history reaches the prompt and the window still fits. The
latencies above are recorded in the commit; a timing assertion in a merge gate is a flake, not
a guard.
"""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

import pytest

AGENT_DIR = Path(__file__).resolve().parents[1]
if str(AGENT_DIR) not in sys.path:
    sys.path.insert(0, str(AGENT_DIR))

HISTORY = [
    {"role": "user", "content": "my worker double-fires when the queue saturates"},
    {"role": "assistant", "content": "The backoff resets inside the except branch, so a second failure restarts the timer."},
    {"role": "user", "content": "i renamed it to RetryPolicy"},
    {"role": "assistant", "content": "Noted — RetryPolicy it is."},
    {"role": "user", "content": "and i moved it to workers/retry.py"},
    {"role": "assistant", "content": "Got it, workers/retry.py."},
]


@pytest.fixture()
def isolated(monkeypatch, tmp_path):
    monkeypatch.setenv("LAYLA_DATA_DIR", str(tmp_path))
    import runtime_safety as rs
    rs.invalidate_config_cache()
    yield
    rs.invalidate_config_cache()


def _force_convo_turns(monkeypatch, n: int) -> None:
    """Pin the EFFECTIVE convo_turns for a test.

    These tests must not assert on the operator's own runtime_config.json. This machine's config
    literally contains `"convo_turns": 0` — a stored copy of the old shipped default — so an
    assertion on `load_config()` would test one person's file rather than the product, and would
    fail on their box while passing everywhere else. The MECHANISM (does history reach the prompt
    when the value is > 0) and the SHIPPED DEFAULT are the two things that belong in a test; the
    operator's stored preference is theirs.
    """
    import runtime_safety as rs
    real = rs.load_config
    monkeypatch.setattr(rs, "load_config", lambda: {**real(), "convo_turns": n})


def _capture_prompt(monkeypatch, history, goal="what did i rename it to?"):
    """Drive the REAL stream_reason and return the prompt the model would have received.

    Signature-agnostic on purpose: the first version of this spy declared (cfg, prompt) and was
    never called, which reported "not captured" rather than a false pass. A probe that cannot
    tell "the thing is broken" from "my hook missed" is worse than no probe.
    """
    captured: dict = {}

    def _spy(*a, **kw):
        captured["prompt"] = kw.get("prompt") if "prompt" in kw else (a[0] if a else None)
        raise RuntimeError("STOP - prompt captured")

    import services.agent.stream_handler as sh
    import services.llm.llm_gateway as gw
    monkeypatch.setattr(gw, "run_completion", _spy, raising=False)
    if hasattr(sh, "run_completion"):
        monkeypatch.setattr(sh, "run_completion", _spy, raising=False)

    try:
        for _ in sh.stream_reason(goal=goal, conversation_history=history, aspect_id="morrigan"):
            break
    except Exception as exc:  # noqa: BLE001 — the sentinel is how we stop before generating
        if "STOP" not in str(exc):
            raise
    assert captured.get("prompt"), (
        "the prompt was never captured, so this test proves nothing either way — the spy is not "
        "on the real call path any more. Fix the hook before trusting a pass."
    )
    return captured["prompt"]


def test_she_can_see_her_own_previous_replies(isolated, monkeypatch):
    """THE POINT. Her own earlier answer must be in the prompt, not just the user's messages."""
    _force_convo_turns(monkeypatch, 6)
    prompt = _capture_prompt(monkeypatch, HISTORY)
    assert "Recent conversation:" in prompt, (
        "the conversation block was not appended at all — convo_turns is 0 again, so she cannot "
        "see her own previous replies and every follow-up question is unanswerable"
    )
    assert "backoff resets inside the except branch" in prompt, (
        "her OWN earlier reply is missing from the prompt. She can see what you said and not what "
        "she answered, which is the half that makes a conversation incoherent."
    )


def test_a_fact_stated_only_in_conversation_survives_to_the_next_turn(isolated, monkeypatch):
    """The user-visible symptom: 'what did I rename it to?' must be answerable from the prompt."""
    _force_convo_turns(monkeypatch, 6)
    prompt = _capture_prompt(monkeypatch, HISTORY)
    for fact in ("RetryPolicy", "workers/retry.py"):
        assert fact in prompt, (
            "%r was stated in conversation and is absent from the prompt, so the model cannot "
            "answer a question about it however well it reasons" % fact
        )


def test_the_shipped_default_is_not_zero():
    """The DEFAULT, read from source — not the effective value.

    Asserting `load_config()` here would assert the operator's own file. This box stores
    `"convo_turns": 0`, a copy of the old default written before it was settable, so an effective
    assertion fails on the one machine that matters while passing in CI. Read the default the
    product ships instead.
    """
    import ast

    tree = ast.parse((AGENT_DIR / "runtime_safety.py").read_text(encoding="utf-8"))
    found = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Dict):
            for k, v in zip(node.keys, node.values):
                if isinstance(k, ast.Constant) and k.value == "convo_turns":
                    if isinstance(v, ast.Constant) and isinstance(v.value, int):
                        found.append(v.value)
    assert found, "convo_turns is no longer in runtime_safety's defaults at all"
    assert all(n > 0 for n in found), (
        "the shipped default for convo_turns is %r — the 'Recent conversation' block is gated on "
        "`> 0`, so 0 silently removes her memory of the conversation while nothing else fails" % found
    )


def test_convo_turns_is_settable_and_no_owner_reverts_it(isolated):
    """A setting nobody can reach, or one auto-tune overwrites, is not a setting.

    This key was absent from the schema entirely, so there was no way to turn history on even
    after discovering it was off.
    """
    from install.feature_status import writable_config_keys
    from services.infrastructure.auto_tune import PROFILE_KEYS

    assert "convo_turns" in writable_config_keys(), (
        "convo_turns is not writable, so an operator cannot change how much of the conversation "
        "Layla sees"
    )
    assert "convo_turns" not in PROFILE_KEYS, (
        "auto-tune owns convo_turns, so whatever the operator sets is overwritten on the next "
        "config load — the exact silent-revert this project has fixed repeatedly"
    )


def test_the_schema_cap_keeps_the_prompt_inside_the_window(isolated):
    """The ceiling is the context window. Above it the prompt no longer fits and the model
    silently loses the far end of whatever it was given."""
    from config_schema import EDITABLE_SCHEMA

    entry = next((f for f in EDITABLE_SCHEMA if f.get("key") == "convo_turns"), None)
    assert entry is not None, "convo_turns vanished from the editable schema"
    cap = int(entry["max"])

    def history_tokens(n: int) -> int:
        # stream_handler: the last 2 messages get 600 chars, older ones 220. ~4 chars/token.
        return int(sum(600 if (n - i) <= 2 else 220 for i in range(n)) / 4)

    HEAD, REPLY, USER = 860, 320, 30  # measured head, reply reserve, a short user turn
    assert HEAD + REPLY + USER + history_tokens(cap) <= 2048, (
        "at the schema maximum of %d the prompt is ~%d tokens against a 2048 window — the cap "
        "permits an overflow" % (cap, HEAD + REPLY + USER + history_tokens(cap))
    )
    assert HEAD + REPLY + USER + history_tokens(cap + 2) > 2048, (
        "the cap of %d is far below the real ceiling; it should not be more conservative than "
        "the window requires" % cap
    )
