"""Route-level smoke for the voice endpoints (previously untested). They must be
registered and degrade gracefully (structured JSON, never an unhandled 500) whether or
not an STT/TTS engine is installed."""
from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from routers import voice as voice_router


def _client():
    app = FastAPI(); app.include_router(voice_router.router)
    return TestClient(app, raise_server_exceptions=False)


def test_transcribe_empty_body_is_400():
    r = _client().post("/voice/transcribe", content=b"")
    assert r.status_code == 400
    assert r.json()["ok"] is False


def test_transcribe_with_audio_but_no_engine_is_graceful():
    # No faster-whisper in the test env → 503 with a recovery hint, not a crash.
    r = _client().post("/voice/transcribe", content=b"\x00\x01fakeaudio")
    assert r.status_code in (200, 503)
    assert r.status_code != 404


def test_speak_empty_text_is_400():
    r = _client().post("/voice/speak", json={"text": ""})
    assert r.status_code == 400


def test_speak_with_text_is_registered_and_graceful():
    r = _client().post("/voice/speak", json={"text": "hello"})
    # 200 (audio) if a TTS engine is present, else 503 with recovery — never 404/unhandled-500.
    assert r.status_code in (200, 503)
