"""BL-155: Layla CLI client — SSE parsing, one-shot + non-stream, error handling."""
from __future__ import annotations

import io
import json

from clients import layla_cli as cli


class _FakeResp:
    def __init__(self, lines=None, body=None):
        self._lines = lines or []
        self._body = body

    def __iter__(self):
        return iter(self._lines)

    def read(self):
        return self._body


def test_iter_sse_extracts_deltas():
    lines = [
        b'data: {"choices":[{"delta":{"role":"assistant"}}]}',
        b'data: {"choices":[{"delta":{"content":"Hel"}}]}',
        b'data: {"choices":[{"delta":{"content":"lo"}}]}',
        b'data: [DONE]',
        b'data: {"choices":[{"delta":{"content":"IGNORED"}}]}',
    ]
    assert list(cli._iter_sse(_FakeResp(lines))) == ["Hel", "lo"]


def test_complete_stream(monkeypatch):
    lines = [
        b'data: {"choices":[{"delta":{"content":"hi "}}]}',
        b'data: {"choices":[{"delta":{"content":"there"}}]}',
        b'data: [DONE]',
    ]
    monkeypatch.setattr(cli, "_post", lambda base, payload, timeout: _FakeResp(lines))
    out = io.StringIO()
    text = cli.complete("http://x", [{"role": "user", "content": "hey"}], stream=True, out=out)
    assert text == "hi there"
    assert "hi there" in out.getvalue()


def test_complete_non_stream(monkeypatch):
    body = json.dumps({"choices": [{"message": {"role": "assistant", "content": "the answer"}}]}).encode()
    captured = {}

    def _fake_post(base, payload, timeout):
        captured["payload"] = payload
        return _FakeResp(body=body)

    monkeypatch.setattr(cli, "_post", _fake_post)
    out = io.StringIO()
    text = cli.complete("http://x", [{"role": "user", "content": "q"}], model="layla-nyx",
                        stream=False, out=out)
    assert text == "the answer"
    assert captured["payload"]["model"] == "layla-nyx" and captured["payload"]["stream"] is False


def test_complete_connection_error(monkeypatch):
    import urllib.error

    def _boom(base, payload, timeout):
        raise urllib.error.URLError("refused")

    monkeypatch.setattr(cli, "_post", _boom)
    assert cli.complete("http://x", [{"role": "user", "content": "q"}]) == ""


def test_main_one_shot(monkeypatch):
    calls = {}

    def _fake_complete(base, messages, **kw):
        calls["messages"] = messages
        calls["model"] = kw.get("model")
        return "ok"

    monkeypatch.setattr(cli, "complete", _fake_complete)
    rc = cli.main(["--model", "layla", "hello", "world"])
    assert rc == 0
    assert calls["messages"] == [{"role": "user", "content": "hello world"}]
