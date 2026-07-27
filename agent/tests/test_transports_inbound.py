"""Isolated tests for the first-class chat-transport layer (transports/).

Covers the shared base adapter and the Slack/Telegram bot start behavior WITHOUT
touching real Slack/Telegram or a live Layla server:

  (a) a fake inbound message flows through the base adapter -> the run path is
      invoked with allow_write == allow_run == False, and the reply comes back;
  (b) a non-allowlisted sender is refused and the agent is NEVER called;
  (c) a missing token makes each bot refuse to start cleanly (returns None, no
      crash);
  (d) each bot degrades gracefully when its optional library is absent.

The run path is stubbed (injected runner / patched module fn), so no network.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# Import the repo-level transports package fresh (avoid a stale cached module).
for _k in [k for k in list(sys.modules) if k == "transports" or k.startswith("transports.")]:
    del sys.modules[_k]

from transports import base as tb  # noqa: E402
from transports.base import TransportAdapter  # noqa: E402


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------
def _open_security(monkeypatch):
    """Force the shared gate into 'open' mode (no allowlist, no pairing)."""
    monkeypatch.setattr(
        tb,
        "get_inbound_transport_security",
        lambda: {
            "allowlist": set(),
            "pairing_secret": "",
            "transport_require_allowlist": False,
            "misconfigured": False,
        },
    )


def _allowlist_only(monkeypatch, allowlist):
    monkeypatch.setattr(
        tb,
        "get_inbound_transport_security",
        lambda: {
            "allowlist": set(allowlist),
            "pairing_secret": "",
            "transport_require_allowlist": False,
            "misconfigured": False,
        },
    )


class _RecordingRunner:
    """Stub run path that records the kwargs it was called with."""

    def __init__(self, reply="stub-reply"):
        self.reply = reply
        self.calls: list[dict] = []

    async def async_call(self, message, **kwargs):
        self.calls.append({"message": message, **kwargs})
        return self.reply

    def sync_call(self, message, **kwargs):
        self.calls.append({"message": message, **kwargs})
        return self.reply


# ---------------------------------------------------------------------------
# (a) inbound -> run path with allow_write == allow_run == False -> reply
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_inbound_reaches_run_path_with_write_and_run_forced_false(monkeypatch):
    _open_security(monkeypatch)
    runner = _RecordingRunner(reply="hello from Layla")
    adapter = TransportAdapter("telegram", async_runner=runner.async_call)

    result = await adapter.handle_inbound_async(chat_id="chat-1", user_id="u1", text="hi there")

    assert result.allowed is True
    assert result.ran_agent is True
    assert result.reply == "hello from Layla"
    assert len(runner.calls) == 1
    call = runner.calls[0]
    assert call["message"] == "hi there"
    # The load-bearing security invariant: transport turns never get write/run.
    assert call["allow_write"] is False
    assert call["allow_run"] is False


def test_inbound_sync_forces_write_and_run_false(monkeypatch):
    _open_security(monkeypatch)
    runner = _RecordingRunner(reply="sync reply")
    adapter = TransportAdapter("slack", sync_runner=runner.sync_call)

    result = adapter.handle_inbound_sync(chat_id="C123", user_id="U1", text="ping")

    assert result.allowed is True and result.reply == "sync reply"
    assert runner.calls[0]["allow_write"] is False
    assert runner.calls[0]["allow_run"] is False


def test_default_run_path_is_call_layla(monkeypatch):
    """With no injected runner, the adapter uses the module-level call_layla_* fn
    (patched here) and still forces the flags False."""
    _open_security(monkeypatch)
    seen = {}

    def fake_sync(message, **kwargs):
        seen.update(message=message, **kwargs)
        return "patched"

    monkeypatch.setattr(tb, "call_layla_sync", fake_sync)
    adapter = TransportAdapter("slack")
    result = adapter.handle_inbound_sync(chat_id="c", user_id="u", text="yo")
    assert result.reply == "patched"
    assert seen["allow_write"] is False and seen["allow_run"] is False


# ---------------------------------------------------------------------------
# (a') per-conversation history keyed by chat id
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_history_is_keyed_by_chat_id(monkeypatch):
    _open_security(monkeypatch)
    runner = _RecordingRunner()
    adapter = TransportAdapter("telegram", async_runner=runner.async_call)

    await adapter.handle_inbound_async(chat_id="A", user_id="u", text="first")
    await adapter.handle_inbound_async(chat_id="A", user_id="u", text="second")
    # A different chat starts with empty context — no cross-chat bleed.
    await adapter.handle_inbound_async(chat_id="B", user_id="u", text="only-B")

    # Second turn on chat A carried the first turn as context.
    ctx_second_a = runner.calls[1]["context"]
    assert "first" in ctx_second_a
    # Chat B's turn saw nothing from chat A.
    ctx_b = runner.calls[2]["context"]
    assert "first" not in ctx_b and "second" not in ctx_b
    assert adapter.conversation_key("A") == "telegram:A"


# ---------------------------------------------------------------------------
# (b) a non-allowlisted sender is refused, agent never called
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_non_allowlisted_sender_is_refused(monkeypatch):
    _allowlist_only(monkeypatch, {"telegram:999"})
    runner = _RecordingRunner()
    adapter = TransportAdapter("telegram", async_runner=runner.async_call)

    result = await adapter.handle_inbound_async(chat_id="chat", user_id="123", text="let me in")

    assert result.allowed is False
    assert result.ran_agent is False
    assert result.reply and "Unauthorized" in result.reply
    assert runner.calls == []  # agent was NEVER invoked


@pytest.mark.asyncio
async def test_allowlisted_sender_is_admitted(monkeypatch):
    _allowlist_only(monkeypatch, {"telegram:999"})
    runner = _RecordingRunner(reply="ok")
    adapter = TransportAdapter("telegram", async_runner=runner.async_call)

    result = await adapter.handle_inbound_async(chat_id="chat", user_id="999", text="hi")
    assert result.allowed is True and result.reply == "ok"
    assert len(runner.calls) == 1


# ---------------------------------------------------------------------------
# (c) missing token -> the bot refuses to start cleanly (no crash)
# ---------------------------------------------------------------------------
def _import_bot(name):
    for _k in [k for k in list(sys.modules) if k.startswith(f"transports.{name}")]:
        del sys.modules[_k]
    import importlib

    return importlib.import_module(f"transports.{name}")


def _has(mod_name):
    import importlib.util

    return importlib.util.find_spec(mod_name) is not None


@pytest.mark.skipif(not _has("telegram"), reason="python-telegram-bot not installed")
def test_telegram_refuses_without_token(monkeypatch):
    bot = _import_bot("telegram_bot")
    monkeypatch.setattr(bot, "_get_token", lambda: "")
    assert bot.build_app() is None  # clean refusal, no crash


@pytest.mark.skipif(not _has("slack_bolt"), reason="slack-bolt not installed")
def test_slack_refuses_without_bot_token(monkeypatch):
    bot = _import_bot("slack_bot")
    monkeypatch.setattr(bot, "_get_token", lambda: "")
    monkeypatch.setattr(bot, "_get_app_token", lambda: "xapp-present")
    assert bot.build_app() is None


@pytest.mark.skipif(not _has("slack_bolt"), reason="slack-bolt not installed")
def test_slack_refuses_without_app_token(monkeypatch):
    bot = _import_bot("slack_bot")
    monkeypatch.setattr(bot, "_get_token", lambda: "xoxb-present")
    monkeypatch.setattr(bot, "_get_app_token", lambda: "")
    assert bot.build_app() is None


# ---------------------------------------------------------------------------
# (d) degrade cleanly when the optional lib is absent
# ---------------------------------------------------------------------------
def test_telegram_degrades_without_lib(monkeypatch):
    # Make `import telegram` raise ImportError even if it is installed.
    monkeypatch.setitem(sys.modules, "telegram", None)
    monkeypatch.setitem(sys.modules, "telegram.ext", None)
    bot = _import_bot("telegram_bot")
    # Present a token so we know None is due to the missing lib, not the token.
    monkeypatch.setattr(bot, "_get_token", lambda: "token-123")
    assert bot.build_app() is None  # degrades, does not raise


def test_slack_degrades_without_lib(monkeypatch):
    monkeypatch.setitem(sys.modules, "slack_bolt", None)
    monkeypatch.setitem(sys.modules, "slack_bolt.adapter.socket_mode", None)
    bot = _import_bot("slack_bot")
    monkeypatch.setattr(bot, "_get_token", lambda: "xoxb")
    monkeypatch.setattr(bot, "_get_app_token", lambda: "xapp")
    assert bot.build_app() is None


# ---------------------------------------------------------------------------
# adapter guardrails
# ---------------------------------------------------------------------------
def test_adapter_requires_platform():
    with pytest.raises(ValueError):
        TransportAdapter("")
