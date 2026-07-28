# -*- coding: utf-8 -*-
"""
/v1 chat-completions: tools / tool_choice / response_format handling.

Layla's /v1 runs its own internal agent tools; it does NOT do OpenAI client-side function-calling
passthrough. Silently returning prose to a client that REQUIRES a tool call hands back a response
the client cannot parse, so the endpoint fails clearly instead. A client that merely OFFERS tools
with the default "auto" choice is valid and must not be rejected. response_format json_object is
honored best-effort via an output directive.
"""
from __future__ import annotations

import sys
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

AGENT_DIR = Path(__file__).resolve().parent.parent
if str(AGENT_DIR) not in sys.path:
    sys.path.insert(0, str(AGENT_DIR))

from routers import openai_compat as oc  # noqa: E402


def _client():
    app = FastAPI()
    app.include_router(oc.router)
    return TestClient(app)


def _post(tool_choice=None, response_format=None, extra=None):
    body = {"model": "layla", "messages": [{"role": "user", "content": "hello"}]}
    if tool_choice is not None:
        body["tool_choice"] = tool_choice
    if response_format is not None:
        body["response_format"] = response_format
    if extra:
        body.update(extra)
    return _client().post("/v1/chat/completions", json=body)


def test_tool_choice_required_is_rejected_clearly():
    r = _post(tool_choice="required")
    assert r.status_code == 400
    err = r.json().get("error", {})
    assert err.get("code") == "tool_choice_unsupported"
    assert err.get("param") == "tool_choice"


def test_tool_choice_named_function_is_rejected():
    r = _post(tool_choice={"type": "function", "function": {"name": "get_weather"}})
    assert r.status_code == 400
    assert r.json().get("error", {}).get("code") == "tool_choice_unsupported"


def test_tool_choice_auto_proceeds_past_the_tool_guard():
    # "auto" (merely OFFERING tools) must NOT trip the tool_choice guard — it proceeds into the
    # normal handler, which then fails only for lack of an initialized app/runtime in this bare
    # TestClient. That downstream failure proves it got past our early 400 (which would have been a
    # clean JSON response, not a raised runtime error).
    import pytest
    with pytest.raises(Exception) as ei:  # noqa: PT011 — asserting on message below
        _post(tool_choice="auto", extra={"tools": [{"type": "function", "function": {"name": "x"}}]})
    assert "tool_choice" not in str(ei.value).lower()
