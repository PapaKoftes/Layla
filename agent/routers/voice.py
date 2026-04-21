"""Voice STT/TTS endpoints."""
from __future__ import annotations

import asyncio
import logging

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, Response

logger = logging.getLogger("layla")
router = APIRouter(tags=["voice"])


@router.post("/voice/transcribe")
async def voice_transcribe(request: Request):
    """Transcribe audio to text using faster-whisper."""
    try:
        from services.stt import get_stt_recovery, is_stt_ready, transcribe_bytes

        audio_bytes = await request.body()
        if not audio_bytes:
            return JSONResponse({"ok": False, "error": "No audio data"}, status_code=400)
        if not is_stt_ready():
            rec = get_stt_recovery()
            return JSONResponse(
                {
                    "ok": False,
                    "text": "",
                    "error": "Speech-to-text is not available",
                    "recovery": rec or {"what_failed": "faster-whisper not loaded"},
                },
                status_code=503,
            )
        text = await asyncio.to_thread(transcribe_bytes, audio_bytes)
        return JSONResponse({"ok": True, "text": text})
    except Exception as e:
        logger.warning("STT error: %s", e)
        return JSONResponse({"ok": False, "error": str(e)}, status_code=500)


@router.post("/voice/speak")
async def voice_speak(request: Request):
    """Text-to-speech via kokoro-onnx (or pyttsx3 fallback)."""
    try:
        from services.tts import get_tts_recovery, speak_to_bytes

        body = await request.body()
        aspect_id = ""
        speed_override = None
        try:
            import json as _j

            data = _j.loads(body)
            text = data.get("text", "")
            aspect_id = str(data.get("aspect_id", "")).strip().lower()
        except Exception:
            text = body.decode("utf-8", errors="replace").strip()
        if not text:
            return JSONResponse({"ok": False, "error": "No text provided"}, status_code=400)
        # Map aspect → TTS speed (matches TTS_VOICE_STYLES in layla-app.js)
        _ASPECT_SPEEDS = {
            "morrigan": 1.05, "nyx": 0.82, "echo": 0.90,
            "eris": 1.20, "cassandra": 1.15, "lilith": 0.78,
        }
        if aspect_id in _ASPECT_SPEEDS:
            speed_override = _ASPECT_SPEEDS[aspect_id]
        wav = await asyncio.to_thread(speak_to_bytes, text, speed_override)
        if wav is None:
            rec = get_tts_recovery()
            return JSONResponse(
                {
                    "ok": False,
                    "error": "TTS not available",
                    "recovery": rec
                    or {
                        "what_failed": "No TTS engine",
                        "next_steps": ["pip install kokoro-onnx soundfile", "or: pip install pyttsx3"],
                    },
                },
                status_code=503,
            )
        return Response(content=wav, media_type="audio/wav")
    except Exception as e:
        logger.warning("TTS error: %s", e)
        return JSONResponse({"ok": False, "error": str(e)}, status_code=500)
