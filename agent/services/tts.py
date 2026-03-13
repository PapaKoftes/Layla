"""
Text-to-Speech service using kokoro-onnx (offline, high-quality, fast on CPU).

Install: pip install kokoro-onnx soundfile
Model downloads automatically on first call (~80 MB ONNX weights).

Fallback: pyttsx3 (system TTS, zero download, lower quality).
Falls back gracefully if neither is installed.

Usage:
    from services.tts import speak_to_bytes
    wav_bytes = speak_to_bytes("Hello, I'm Layla.")  # returns WAV bytes
"""
from __future__ import annotations

import io
import logging
import threading

logger = logging.getLogger("layla.tts")

_tts_engine = None
_tts_lock = threading.Lock()
_tts_type: str = ""  # "kokoro" | "pyttsx3" | ""
_tts_failed = False

# Voice selection for kokoro-onnx.
# Available voices: af (female), am (male), bf (British female), bm (British male)
# Full list at https://github.com/thewh1teagle/kokoro-onnx
_DEFAULT_VOICE = "af_heart"  # warm American female
_DEFAULT_SPEED = 1.0


def _init_kokoro():
    """Try to load kokoro-onnx TTS."""
    global _tts_engine, _tts_type
    from kokoro_onnx import Kokoro
    try:
        import runtime_safety
        cfg = runtime_safety.load_config()
        voice = cfg.get("tts_voice", _DEFAULT_VOICE)
        speed = float(cfg.get("tts_speed", _DEFAULT_SPEED))
    except Exception:
        voice = _DEFAULT_VOICE
        speed = _DEFAULT_SPEED
    _tts_engine = Kokoro(voice=voice, speed=speed)
    _tts_type = "kokoro"
    logger.info("TTS: kokoro-onnx loaded (voice=%s speed=%.1f)", voice, speed)


def _init_pyttsx3():
    """Fallback: system TTS via pyttsx3."""
    global _tts_engine, _tts_type
    import pyttsx3
    engine = pyttsx3.init()
    engine.setProperty("rate", 175)
    engine.setProperty("volume", 1.0)
    # Prefer a female voice if available
    voices = engine.getProperty("voices")
    for v in (voices or []):
        if "female" in (v.name or "").lower() or "zira" in (v.name or "").lower():
            engine.setProperty("voice", v.id)
            break
    _tts_engine = engine
    _tts_type = "pyttsx3"
    logger.info("TTS: pyttsx3 fallback loaded")


def _get_tts():
    global _tts_engine, _tts_failed
    if _tts_failed:
        return None
    if _tts_engine is not None:
        return _tts_engine
    with _tts_lock:
        if _tts_engine is not None:
            return _tts_engine
        try:
            _init_kokoro()
        except ImportError:
            try:
                _init_pyttsx3()
            except ImportError:
                logger.warning(
                    "No TTS engine available. Install: pip install kokoro-onnx soundfile"
                )
                _tts_failed = True
        except Exception as e:
            logger.warning("TTS init failed: %s", e)
            _tts_failed = True
    return _tts_engine


def speak_to_bytes(text: str) -> bytes | None:
    """
    Convert text to speech. Returns WAV bytes, or None on failure.
    Suitable for streaming from the /voice/speak API endpoint.
    """
    engine = _get_tts()
    if engine is None:
        return None
    # Truncate very long text to avoid huge audio files
    text = text.strip()[:2000]
    if not text:
        return None

    try:
        if _tts_type == "kokoro":
            import soundfile as sf
            samples, sample_rate = engine.create(text)
            buf = io.BytesIO()
            sf.write(buf, samples, sample_rate, format="WAV")
            return buf.getvalue()

        elif _tts_type == "pyttsx3":
            # pyttsx3 can save to file; use a temp file
            import tempfile
            import os
            with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
                fname = f.name
            try:
                engine.save_to_file(text, fname)
                engine.runAndWait()
                with open(fname, "rb") as f:
                    return f.read()
            finally:
                try:
                    os.unlink(fname)
                except Exception:
                    pass

    except Exception as e:
        logger.warning("TTS synthesis failed: %s", e)
        return None


def prewarm() -> None:
    """Load the TTS model in a background thread at startup."""
    t = threading.Thread(target=_get_tts, daemon=True, name="tts-prewarm")
    t.start()
