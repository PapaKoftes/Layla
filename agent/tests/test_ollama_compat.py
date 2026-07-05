"""BL-152: the Ollama-native API surface (/api/tags, /api/chat, /api/generate, /api/version)."""
from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient

from routers import ollama_compat as oc


@pytest.fixture()
def client(monkeypatch):
    # Stub the reused OpenAI handler so we don't need a live model.
    async def _fake_v1(oai, request):
        msg = (oai.get("messages") or [{}])[-1].get("content", "")
        return JSONResponse({
            "object": "chat.completion",
            "model": "layla-morrigan",
            "choices": [{"index": 0, "message": {"role": "assistant", "content": f"echo: {msg}"}, "finish_reason": "stop"}],
        })
    monkeypatch.setattr("routers.openai_compat.v1_chat_completions", _fake_v1)
    app = FastAPI()
    app.include_router(oc.router)
    return TestClient(app)


def test_version(client):
    assert "version" in client.get("/api/version").json()


def test_tags_lists_layla_and_aspects(client):
    d = client.get("/api/tags").json()
    names = [m["name"] for m in d["models"]]
    assert "layla" in names
    assert "layla-morrigan" in names
    assert all("details" in m and "digest" in m for m in d["models"])  # ollama tag shape


def test_chat_translates_to_ollama_shape(client):
    r = client.post("/api/chat", json={"model": "layla", "messages": [{"role": "user", "content": "hi there"}]})
    assert r.status_code == 200
    d = r.json()
    assert d["done"] is True and d["message"]["role"] == "assistant"
    assert d["message"]["content"] == "echo: hi there"


def test_generate_translates_prompt(client):
    r = client.post("/api/generate", json={"model": "layla", "prompt": "who are you"})
    assert r.status_code == 200
    d = r.json()
    assert d["done"] is True and d["response"] == "echo: who are you"
