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

logger = logging.getLogger("layla.stt")

_model = None
_model_lock = threading.Lock()
_model_failed = False
_stt_recovery: dict | None = None

# Use "base" for speed (~50 MB), "small" for better accuracy (~150 MB),
# "medium" or "large-v3" for near-perfect accuracy.
# Overridable via runtime_config.json: {"whisper_model": "small"}
_DEFAULT_MODEL = "base"


def _get_model():
    global _model, _model_failed, _stt_recovery
    if _model_failed:
        return None
    if _model is not None:
        return _model
    with _model_lock:
        if _model is not None:
            return _model
        try:
            try:
                from faster_whisper import WhisperModel
            except ImportError:
                import runtime_safety
                from services.dependency_recovery import ensure_feature, merge_recovery_message

                _cfg = runtime_safety.load_config()
                ok, rec = ensure_feature("faster_whisper", _cfg)
                _stt_recovery = rec
                if ok:
                    from faster_whisper import WhisperModel
                else:
                    logger.warning("STT unavailable: %s", merge_recovery_message(rec or {}))
                    _model_failed = True
                    return None
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
            _stt_recovery = None
        except Exception as e:
            logger.warning("Whisper model load failed: %s", e)
            _model_failed = True
            _stt_recovery = {
                "what_failed": "Whisper model failed to load after import succeeded",
                "exception": str(e),
                "next_steps": [
                    "Check disk space and Hugging Face cache (~/.cache/huggingface).",
                    "Try a smaller whisper_model in runtime_config.json (e.g. base).",
                    "See agent/runtime_config.example.json for whisper_model / whisper_device.",
                ],
            }
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


def detect_voice_mode(audio_bytes: bytes, min_duration_ms: int = 500) -> bool:
    """
    Detect if audio contains speech (vs silence). Used for automatic voice mode.
    Returns True if audio has sufficient duration and non-trivial content.
    """
    if not audio_bytes or len(audio_bytes) < 1000:
        return False
    try:
        import struct
        # WAV: 44-byte header, then 16-bit samples
        if audio_bytes[:4] == b"RIFF" and len(audio_bytes) > 44:
            samples = audio_bytes[44:]
            if len(samples) < 2:
                return False
            # Sample every 100th value to avoid full scan
            step = max(1, len(samples) // 200)
            vals = [struct.unpack_from("<h", samples, i)[0] for i in range(0, len(samples) - 2, step)]
            rms = (sum(v * v for v in vals) / max(1, len(vals))) ** 0.5
            return rms > 100  # non-silent
        return len(audio_bytes) > 2000  # assume speech if long enough
    except Exception:
        return len(audio_bytes) > 2000


def transcribe_streaming(audio_bytes: bytes, language: str | None = None):
    """
    Transcribe audio, yielding partial transcripts as segments complete.
    Yields (text_so_far, is_final) tuples.
    """
    model = _get_model()
    if model is None:
        yield ("", True)
        return
    try:
        audio_io = io.BytesIO(audio_bytes)
        segments, info = model.transcribe(
            audio_io,
            language=language,
            beam_size=5,
            vad_filter=True,
            vad_parameters={"min_silence_duration_ms": 500},
        )
        acc = []
        for seg in segments:
            t = (seg.text or "").strip()
            if t:
                acc.append(t)
                yield (" ".join(acc), False)
        yield (" ".join(acc), True)
    except Exception as e:
        logger.warning("Streaming transcription failed: %s", e)
        yield ("", True)


def prewarm() -> None:
    """Load the Whisper model in a background thread at startup."""
    t = threading.Thread(target=_get_model, daemon=True, name="whisper-prewarm")
    t.start()


def get_stt_recovery() -> dict | None:
    """Last structured recovery info when STT is unavailable (for API/UI)."""
    return _stt_recovery


def is_stt_ready() -> bool:
    """False when faster-whisper cannot be loaded (import or model init failure)."""
    if _model_failed:
        return False
    return _get_model() is not None
