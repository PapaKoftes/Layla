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
_tts_recovery: dict | None = None

# Voice selection for kokoro-onnx.
# Available voices: af_heart, af_bella, af_sarah, am_adam, am_michael,
# bf_emma, bf_sarah, bm_george, bm_lewis — see kokoro-onnx docs
_DEFAULT_VOICE = "af_heart"  # warm American female
_DEFAULT_SPEED = 1.0

# Configurable voice catalog for UI/settings
AVAILABLE_VOICES = [
    ("af_heart", "American female (warm)"),
    ("af_bella", "American female (Bella)"),
    ("af_sarah", "American female (Sarah)"),
    ("am_adam", "American male (Adam)"),
    ("am_michael", "American male (Michael)"),
    ("bf_emma", "British female (Emma)"),
    ("bf_sarah", "British female (Sarah)"),
    ("bm_george", "British male (George)"),
    ("bm_lewis", "British male (Lewis)"),
]


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
    global _tts_engine, _tts_failed, _tts_recovery
    if _tts_failed:
        return None
    if _tts_engine is not None:
        return _tts_engine
    with _tts_lock:
        if _tts_engine is not None:
            return _tts_engine
        try:
            import runtime_safety
            from services.dependency_recovery import ensure_feature, merge_recovery_message

            _cfg = runtime_safety.load_config()
            _tts_recovery = None

            ok_k, rec_k = ensure_feature("kokoro_tts", _cfg)
            if not ok_k:
                _tts_recovery = rec_k
            else:
                try:
                    _init_kokoro()
                    return _tts_engine
                except Exception as e:
                    logger.warning("TTS kokoro init failed: %s", e)
                    _tts_recovery = {
                        "what_failed": "kokoro-onnx failed to initialize after import",
                        "exception": str(e),
                        "next_steps": [
                            "Try: pip install --upgrade kokoro-onnx soundfile",
                            "Or use system TTS: pip install pyttsx3",
                            "See agent/runtime_config.example.json (tts_voice).",
                        ],
                    }

            ok_p, rec_p = ensure_feature("pyttsx3_tts", _cfg)
            if ok_p:
                try:
                    _init_pyttsx3()
                    _tts_recovery = None
                    return _tts_engine
                except Exception as e:
                    logger.warning("TTS pyttsx3 init failed: %s", e)
                    _tts_recovery = {
                        "what_failed": "pyttsx3 failed to initialize",
                        "exception": str(e),
                        "kokoro_recovery": rec_k,
                        "next_steps": [
                            "pip install pyttsx3",
                            "Or fix kokoro: pip install kokoro-onnx soundfile",
                            "Run: cd agent && python diagnose_startup.py",
                        ],
                    }
            else:
                _tts_recovery = {
                    "what_failed": "No TTS engine available",
                    "kokoro": rec_k if not ok_k else _tts_recovery,
                    "pyttsx3": rec_p,
                    "install_command_primary": "pip install kokoro-onnx soundfile",
                    "install_command_fallback": "pip install pyttsx3",
                    "next_steps": [
                        "1) pip install kokoro-onnx soundfile  (recommended)",
                        "2) pip install pyttsx3  (system voice)",
                        "3) Restart Layla after install.",
                        "4) cd agent && python diagnose_startup.py",
                    ],
                }
                logger.warning("No TTS engine: %s", merge_recovery_message(_tts_recovery))
            _tts_failed = True
        except Exception as e:
            logger.warning("TTS init failed: %s", e)
            _tts_failed = True
            _tts_recovery = {
                "what_failed": str(e),
                "next_steps": [
                    "cd agent && python diagnose_startup.py",
                    "GET http://127.0.0.1:8000/doctor (when server runs)",
                ],
            }
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
            import os
            import tempfile
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


def get_voice_options() -> list[dict]:
    """Return available TTS voices for config/UI. Set tts_voice in runtime_config.json."""
    return [{"id": v[0], "label": v[1]} for v in AVAILABLE_VOICES]


def get_tts_recovery() -> dict | None:
    """Structured recovery when TTS is unavailable (for API/UI)."""
    return _tts_recovery


def prewarm() -> None:
    """Load the TTS model in a background thread at startup."""
    t = threading.Thread(target=_get_tts, daemon=True, name="tts-prewarm")
    t.start()
