"""R19 #7/#8: the /v1 (OpenAI-compat) and /api (Ollama, which routes through /v1) reply cleaners must
thread the active-aspect gate like /agent, so a bare NON-active 'Echo:' definition is preserved instead
of strip-alled. Drives the real non-stream v1_chat_completions strip path with a mocked autonomous_run."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

AGENT_DIR = Path(__file__).resolve().parent.parent
if str(AGENT_DIR) not in sys.path:
    sys.path.insert(0, str(AGENT_DIR))


@pytest.fixture()
def client(monkeypatch):
    from routers import openai_compat as oc

    # No trivial-turn shortcut → force the autonomous_run + final-strip path (openai_compat.py:555).
    monkeypatch.setattr(oc, "_quick_reply_for_trivial_turn", lambda goal: None)
    # shared_state isn't initialized in a bare test app — stub the history appender to a no-op.
    monkeypatch.setattr(oc, "get_append_history", lambda: (lambda role, content: None))

    def _fake_autonomous_run(goal, **kw):
        # A morrigan-aspect turn whose answer is a definition of the NON-active aspect 'Echo'.
        return {"response": "Echo: a sound reflected back to the listener.",
                "aspect": "morrigan", "aspect_name": "Morrigan", "status": "finished", "steps": []}

    monkeypatch.setattr(oc, "autonomous_run", _fake_autonomous_run)
    app = FastAPI()
    app.include_router(oc.router)
    return TestClient(app)


def test_v1_preserves_nonactive_definition_label(client):
    r = client.post("/v1/chat/completions", json={
        "model": "layla-morrigan",
        "stream": False,
        "messages": [{"role": "user", "content": "In one line, what does the word 'echo' mean?"}],
    })
    assert r.status_code == 200
    content = r.json()["choices"][0]["message"]["content"]
    # The active aspect is Morrigan, so 'echo' is NON-active → its definition label must survive
    # (pre-fix the /v1 path passed active_names=None and stripped it to a subjectless fragment).
    assert content.startswith("Echo:"), content
