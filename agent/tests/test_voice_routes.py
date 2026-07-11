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


def test_text_for_speech_strips_markdown_and_code():
    # Round-11: the voice path spoke the visual-markdown reply verbatim, reading code expressions and
    # table separator rows aloud as noise. _text_for_speech projects markdown → plain speech.
    from routers.voice import _text_for_speech as V
    out = V("Fastest way:\n\n1. Use a **set** for O(1) lookups.\n\n| Cmd | Effect |\n|---|---|\n| a | b |")
    assert "**" not in out and "|---|" not in out and "---" not in out
    assert "set for O(1) lookups" in out
    # Fenced code blocks are dropped entirely (reading code char-by-char is noise).
    out2 = V("Here:\n```python\nprint(1)\nprint(2)\n```\nDone.")
    assert "print" not in out2 and "```" not in out2


def test_voice_speak_does_not_truncate_legit_objective_input():
    # Round-11: /voice/speak ran the full reply-scrubber, whose "Objective:" truncation heuristic cut
    # a direct caller's benign "My main objective: …" down to "My main". The light clean must not.
    from routers.voice import _text_for_speech as V
    from services.agent.response_builder import _strip_leading_speaker_label as L
    from services.agent.response_builder import _strip_reasoning_traces as R
    spoken = V(L(R("My main objective: finish the quarterly report.")))
    assert "quarterly report" in spoken
