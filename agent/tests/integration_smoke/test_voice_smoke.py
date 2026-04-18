"""Voice stack smoke: STT + TTS may download models on first run (slow)."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

AGENT_DIR = Path(__file__).resolve().parents[2]
if str(AGENT_DIR) not in sys.path:
    sys.path.insert(0, str(AGENT_DIR))

pytestmark = [pytest.mark.voice_smoke, pytest.mark.timeout(600)]


def test_voice_stt_and_tts_micro():
    from services.stt import transcribe_bytes
    from services.tts import get_tts_recovery, speak_to_bytes

    # Minimal valid WAV payload (mostly silence); STT may return empty string.
    silent_wav = (
        b"RIFF$\x00\x00\x00WAVEfmt \x10\x00\x00\x00\x01\x00\x01\x00"
        b"\x44\xac\x00\x00\x88\x58\x01\x00\x02\x00\x10\x00data\x00\x00\x00\x00"
    )
    transcript = transcribe_bytes(silent_wav)
    assert isinstance(transcript, str)

    audio = speak_to_bytes("Layla voice smoke test.")
    if audio is None:
        rec = get_tts_recovery() or {}
        pytest.skip(f"TTS unavailable in this environment: {rec.get('what_failed') or rec.get('exception') or rec}")
    assert len(audio) > 100, "TTS should return WAV bytes"
