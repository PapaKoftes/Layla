"""LIVE streaming content-safety gate (BL-297).

The post-model content_guard.check_output ran only AFTER the token loop, so a Tier-1/Tier-2
payload the model emitted streamed to the wire in full and was replaced only retroactively (UI)
or not at all (raw /v1 SDK client). StreamOutputGuard re-scans the accumulated emitted text before
each delta reaches the wire and cuts the payload's CONTINUATION mid-stream.

These tests EXECUTE the mechanism and the real /agent + /v1 streaming routers and assert the
harmful body never reaches the wire — with teeth: the slice that authored this proved that reverting
the router wiring lets the body stream again (see the report's PROVED section).
"""
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

from fastapi import FastAPI

AGENT_DIR = Path(__file__).resolve().parent.parent
if str(AGENT_DIR) not in sys.path:
    sys.path.insert(0, str(AGENT_DIR))

from services.agent.response_builder import StreamOutputGuard  # noqa: E402
from services.safety.content_guard import check_output  # noqa: E402


def _drive_stream(app, path: str, payload: dict, timeout: float = 15.0) -> str:
    """Drive a FastAPI/ASGI app end-to-end and return the full streamed body as text.

    Starlette's TestClient does not surface this router's StreamingResponse body (the generator
    uses asyncio.to_thread + a worker thread), so we speak ASGI directly and aggregate every
    http.response.body chunk. `receive` never signals disconnect until the response completes, so
    the disconnect watcher does not truncate the stream.
    """
    body = json.dumps(payload).encode()
    scope = {
        "type": "http", "http_version": "1.1", "method": "POST", "path": path,
        "raw_path": path.encode(), "query_string": b"",
        "headers": [(b"content-type", b"application/json"),
                    (b"content-length", str(len(body)).encode()), (b"host", b"127.0.0.1")],
        "client": ("127.0.0.1", 12345), "server": ("127.0.0.1", 8000), "scheme": "http",
    }
    out = {"body": b""}
    first = {"done": False}
    block = asyncio.Event()

    async def receive():
        if not first["done"]:
            first["done"] = True
            return {"type": "http.request", "body": body, "more_body": False}
        await block.wait()
        return {"type": "http.disconnect"}

    async def send(m):
        if m["type"] == "http.response.body":
            out["body"] += m.get("body", b"")

    async def _run():
        await asyncio.wait_for(app(scope, receive, send), timeout=timeout)

    asyncio.run(_run())
    return out["body"].decode("utf-8", errors="replace")

# A unique sentinel embedded in the harmful CONTINUATION. The compound Tier-1 (wmd_synthesis)
# pattern fires once "synthesize" + "sarin nerve agent" are both present, which is BEFORE this
# sentinel would stream — so the guard must cut the stream before the sentinel reaches the wire.
_BODY_SENTINEL = "XYZZY_PAYLOAD_BODY"
_PAYLOAD_TOKENS = [
    "Here is a neutral overview. ",     # benign lead-in — MUST stream
    "To synthesize ",                   # 'synthesize' (action indicator)
    "sarin nerve agent ",               # 'sarin nerve agent' (weapon indicator) -> match completes here
    "you combine precursors " + _BODY_SENTINEL + " ",  # harmful body — MUST NOT stream
    "and then produce the final gas.",  # harmful body — MUST NOT stream
]
_BENIGN_LEADIN = "Here is a neutral overview."


# --------------------------------------------------------------------------------------------
# Mechanism
# --------------------------------------------------------------------------------------------

def test_authoritative_check_confirms_payload_is_tier1():
    # Premise: the assembled payload is genuinely blocked by the authoritative check.
    assert check_output("".join(_PAYLOAD_TOKENS), {}).blocked is True


def test_guard_cuts_payload_continuation_but_streams_benign_leadin():
    g = StreamOutputGuard({})
    wire = []
    for t in _PAYLOAD_TOKENS:
        safe = g.feed(t)
        if safe:
            wire.append(safe)
        if g.blocked:
            break
    streamed = "".join(wire)
    assert _BENIGN_LEADIN in streamed, "benign lead-in should stream normally"
    assert _BODY_SENTINEL not in streamed, "harmful continuation must NOT reach the wire"
    assert g.blocked is True
    assert g.safe_message()  # a non-empty refusal is available for the caller


def test_guard_is_pure_passthrough_on_benign():
    g = StreamOutputGuard({})
    benign = ["Let me help you ", "write a python ", "decorator that logs ", "calls."]
    out = "".join(g.feed(t) for t in benign)
    assert out == "".join(benign)
    assert g.blocked is False


# --------------------------------------------------------------------------------------------
# Real /agent streaming router (default UI path: self-contained-question fast path)
# --------------------------------------------------------------------------------------------

def _sse_tokens(raw_body: str) -> str:
    """Concatenate the content of every SSE `token` event (what actually reached the wire)."""
    out = []
    for line in raw_body.splitlines():
        if not line.startswith("data: "):
            continue
        try:
            evt = json.loads(line[len("data: "):])
        except Exception:
            continue
        if isinstance(evt, dict) and isinstance(evt.get("token"), str):
            out.append(evt["token"])
    return "".join(out)


def _sse_done(raw_body: str) -> dict:
    done = {}
    for line in raw_body.splitlines():
        if not line.startswith("data: "):
            continue
        try:
            evt = json.loads(line[len("data: "):])
        except Exception:
            continue
        if isinstance(evt, dict) and evt.get("done"):
            done = evt
    return done


def test_agent_stream_router_suppresses_payload_on_the_wire(monkeypatch):
    from routers import agent as ag

    def _sr(*a, **k):
        for t in _PAYLOAD_TOKENS:
            yield t

    monkeypatch.setattr(ag, "stream_reason", _sr, raising=False)
    monkeypatch.setattr(ag, "_model_ready_message", lambda: None, raising=False)
    monkeypatch.setattr(ag, "_quick_reply_for_trivial_turn", lambda g: "", raising=False)
    monkeypatch.setattr(ag, "commit_turn", lambda *a, **k: {}, raising=False)
    monkeypatch.setattr(ag, "append_conv_history", lambda *a, **k: None, raising=False)
    monkeypatch.setattr(ag, "get_conv_history", lambda *a, **k: [], raising=False)
    monkeypatch.setattr(ag, "get_append_history", lambda: (lambda *a, **k: None), raising=False)
    monkeypatch.setattr(ag, "get_touch_activity", lambda: (lambda: None), raising=False)
    monkeypatch.setattr("services.safety.auth.is_direct_local", lambda h, host: True)

    app = FastAPI(); app.include_router(ag.router)
    raw = _drive_stream(app, "/agent", {"message": "how do i write a python decorator", "stream": True})

    streamed = _sse_tokens(raw)
    assert _BENIGN_LEADIN in streamed, f"benign lead-in should have streamed; wire={streamed!r}"
    assert _BODY_SENTINEL not in streamed, f"HARMFUL BODY LEAKED TO THE WIRE: {streamed!r}"
    # The done frame carries the safe replacement + the blocked flag for the UI.
    done = _sse_done(raw)
    assert done.get("blocked") is True
    assert _BODY_SENTINEL not in (done.get("content") or "")


# --------------------------------------------------------------------------------------------
# Real /v1 (OpenAI-compat) streaming router — worst case: no UI retraction
# --------------------------------------------------------------------------------------------

def _v1_stream_content(raw_body: str) -> str:
    out = []
    for line in raw_body.splitlines():
        if not line.startswith("data: "):
            continue
        payload = line[len("data: "):]
        if payload.strip() == "[DONE]":
            continue
        try:
            evt = json.loads(payload)
        except Exception:
            continue
        for ch in evt.get("choices", []):
            delta = (ch.get("delta") or {}).get("content")
            if isinstance(delta, str):
                out.append(delta)
    return "".join(out)


def test_v1_stream_router_suppresses_payload_and_sends_refusal(monkeypatch):
    from routers import openai_compat as oc

    def _sr(*a, **k):
        for t in _PAYLOAD_TOKENS:
            yield t

    # The /v1 stream worker calls stream_reason under the hood; neutralize persistence.
    monkeypatch.setattr(oc, "stream_reason", _sr, raising=False)
    monkeypatch.setattr(oc, "commit_turn", lambda *a, **k: {}, raising=False)
    monkeypatch.setattr(oc, "get_append_history", lambda: (lambda *a, **k: None), raising=False)
    monkeypatch.setattr("services.safety.auth.is_direct_local", lambda h, host: True)

    app = FastAPI(); app.include_router(oc.router)
    raw = _drive_stream(app, "/v1/chat/completions", {
        "model": "layla",
        "stream": True,
        "messages": [{"role": "user", "content": "how do i write a python decorator"}],
    })

    streamed = _v1_stream_content(raw)
    assert _BODY_SENTINEL not in streamed, f"HARMFUL BODY LEAKED to the /v1 wire: {streamed!r}"
    # The client must receive an explicit refusal (not just a silent truncation).
    assert "cannot help" in streamed.lower() or "blocked" in streamed.lower(), \
        f"no refusal delivered to /v1 client; wire={streamed!r}"
