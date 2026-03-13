"""
Speech-to-Text service using faster-whisper (CPU/CUDA, OpenAI Whisper quality).

Install: pip install faster-whisper
Model downloads automatically on first call (cached in ~/.cache/huggingface).

Usage:
    from services.stt import transcribe_bytes, transcribe_file
    text = transcribe_bytes(wav_bytes)  # bytes from browser MediaRecorder
    text = transcribe_file("/path/to/audio.wav")
"""
from __future__ import annotations

import io
import logging
import threading
from pathlib import Path
from typing import Optional

logger = logging.getLogger("layla.stt")

_model = None
_model_lock = threading.Lock()
_model_failed = False

# Use "base" for speed (~50 MB), "small" for better accuracy (~150 MB),
# "medium" or "large-v3" for near-perfect accuracy.
# Overridable via runtime_config.json: {"whisper_model": "small"}
_DEFAULT_MODEL = "base"


def _get_model():
    global _model, _model_failed
    if _model_failed:
        return None
    if _model is not None:
        return _model
    with _model_lock:
        if _model is not None:
            return _model
        try:
            from faster_whisper import WhisperModel
            try:
                import runtime_safety
                cfg = runtime_safety.load_config()
                model_size = cfg.get("whisper_model", _DEFAULT_MODEL)
                device = cfg.get("whisper_device", "auto")
            except Exception:
                model_size = _DEFAULT_MODEL
                device = "auto"
            # "auto" uses CUDA if available, CPU otherwise
            compute = "float16" if device == "cuda" else "int8"
            _model = WhisperModel(model_size, device=device, compute_type=compute)
            logger.info("Whisper model loaded: %s (%s)", model_size, compute)
        except ImportError:
            logger.warning("faster-whisper not installed. Run: pip install faster-whisper")
            _model_failed = True
        except Exception as e:
            logger.warning("Whisper model load failed: %s", e)
            _model_failed = True
    return _model


def transcribe_bytes(audio_bytes: bytes, language: str | None = None) -> str:
    """
    Transcribe audio bytes (WAV/WebM/MP3/OGG) to text.
    Language is auto-detected if not specified.
    Returns the transcript string, or '' on failure.
    """
    model = _get_model()
    if model is None:
        return ""
    try:
        audio_io = io.BytesIO(audio_bytes)
        segments, info = model.transcribe(
            audio_io,
            language=language,
            beam_size=5,
            vad_filter=True,   # skip silence
            vad_parameters={"min_silence_duration_ms": 500},
        )
        text = " ".join(seg.text.strip() for seg in segments).strip()
        logger.info("Transcribed (%s): %s", info.language, text[:100])
        return text
    except Exception as e:
        logger.warning("Transcription failed: %s", e)
        return ""


def transcribe_file(path: str | Path, language: str | None = None) -> str:
    """Transcribe an audio file from disk."""
    model = _get_model()
    if model is None:
        return ""
    try:
        segments, info = model.transcribe(
            str(path),
            language=language,
            beam_size=5,
            vad_filter=True,
        )
        return " ".join(seg.text.strip() for seg in segments).strip()
    except Exception as e:
        logger.warning("File transcription failed: %s", e)
        return ""


def prewarm() -> None:
    """Load the Whisper model in a background thread at startup."""
    t = threading.Thread(target=_get_model, daemon=True, name="whisper-prewarm")
    t.start()
