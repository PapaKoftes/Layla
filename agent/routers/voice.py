"""Voice STT/TTS endpoints."""
from __future__ import annotations

import asyncio
import logging

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, Response

logger = logging.getLogger("layla")
router = APIRouter(tags=["voice"])


def _install_offer() -> dict:
    """The one-click guided-install descriptor attached to every /voice/* 503.

    Turns the dead-feature 503 into an ACTIONABLE offer: it names the permissive `voice`
    feature (faster-whisper MIT + pyttsx3) and the EXISTING allowlisted feature-install
    endpoint the frontend posts to, plus the GPLv3 kokoro upgrade behind an explicit
    accept. Built in install.feature_status so the licensing split lives in one place;
    best-effort so a broken descriptor never turns a graceful 503 into a 500.
    """
    try:
        from install.feature_status import voice_install_descriptor

        return voice_install_descriptor()
    except Exception:
        logger.debug("voice: install descriptor unavailable", exc_info=True)
        return {}


def _text_for_speech(t: str) -> str:
    """Project a reply/markdown string to PLAIN TEXT for TTS. The visual reply cleaners deliberately
    PRESERVE markdown (bold/`code`/tables/headings) for marked.parse, so feeding that same string to
    the synthesizer read code expressions and table separator rows aloud as noise. This strips
    presentation scaffolding meant only for the eye. Non-destructive of prose (no truncation)."""
    import re as _re
    if not t:
        return ""
    # Drop fenced code blocks entirely — reading code aloud char-by-char is noise, not speech.
    t = _re.sub(r"```[^\n]*\n.*?(?:```|\Z)", " ", t, flags=_re.DOTALL)
    # Strip model-emitted inline HTML tags so the synthesizer does not read the markup aloud
    # ("<span class='msg-facet-chip'>Morrigan</span>" → the audio spoke "span class msg-facet-chip
    # Morrigan slash span"). The visible bubble neutralizes HTML via DOMPurify; the audio channel had no
    # equivalent. Drop the tags (keep their text) + decode the few entities marked/DOMPurify emit.
    t = _re.sub(r"</?[A-Za-z][^>]*>", " ", t)
    t = (t.replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">")
          .replace("&quot;", '"').replace("&#39;", "'").replace("&nbsp;", " "))
    # Echoed TITLE-CASE scaffold section headers (memory PII / operator notes / output-discipline) a weak
    # model can restate — the visible bubble strips these via strip_junk_from_reply, but /voice/speak
    # deliberately skips that pass, so without this it SPOKE the stored PII + scaffold aloud. Phrase-
    # specific + body-to-blank-line, mirroring the strip_junk rule (never touches a legit '## Overview').
    t = _re.sub(
        r"(?:^|\n)[ \t]*#{0,3}[ \t]*"
        r"(?:Durable facts about the user|Relationship codex(?:[ \t]*\(operator notes\))?|Output discipline)"
        r"\b[^\n]*(?:\n[^\n]+)*\n*",
        "\n", t, flags=_re.IGNORECASE,
    )
    t = _re.sub(r"~~~[^\n]*\n.*?(?:~~~|\Z)", " ", t, flags=_re.DOTALL)
    _lines = []
    for _ln in t.split("\n"):
        # Drop a markdown table SEPARATOR row ("|---|:--:|") — pure pipes/dashes/colons.
        if "|" in _ln and _re.match(r"^\s*\|?[\s:|-]+\|?\s*$", _ln):
            continue
        # Flatten remaining table cells to comma-separated speech.
        if "|" in _ln:
            _ln = _re.sub(r"\s*\|\s*", ", ", _ln).strip(", ")
        _lines.append(_ln)
    t = "\n".join(_lines)
    t = _re.sub(r"`([^`]*)`", r"\1", t)                       # inline code → its text
    t = _re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", t)           # [label](url) → label
    t = _re.sub(r"[*_~]{1,3}", "", t)                          # bold/italic/strike markers
    t = _re.sub(r"(?m)^\s{0,3}#{1,6}[ \t]*", "", t)           # heading hashes
    t = _re.sub(r"(?m)^\s*>[ \t]?", "", t)                     # blockquote
    t = _re.sub(r"(?m)^\s*[-*+][ \t]+", "", t)                # list bullets
    t = _re.sub(r"(?m)^\s*\d+[.)][ \t]+", "", t)             # numbered list markers
    t = _re.sub(r"[⚔✦◎⚡⌖⊛]️?", "", t)                       # inline aspect sigils
    t = _re.sub(r"\n{2,}", ". ", t)                            # paragraph break → spoken pause
    t = _re.sub(r"[ \t]{2,}", " ", t).strip()
    return t


@router.post("/voice/transcribe")
async def voice_transcribe(request: Request):
    """Transcribe audio to text using faster-whisper."""
    try:
        from services.infrastructure.stt import get_stt_recovery, is_stt_ready, transcribe_bytes

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
                    # One-click guided install: feature id + what it installs + size, mapping to
                    # the allowlisted /setup/feature/install path (never arbitrary pip).
                    "install": _install_offer(),
                    "recovery": rec or {"what_failed": "faster-whisper not loaded"},
                },
                status_code=503,
            )
        text = await asyncio.to_thread(transcribe_bytes, audio_bytes)
        return JSONResponse({"ok": True, "text": text})
    except Exception:
        logger.exception("STT error")
        return JSONResponse({"ok": False, "error": "Transcription failed."}, status_code=500)


@router.post("/voice/speak")
async def voice_speak(request: Request):
    """Text-to-speech via kokoro-onnx (or pyttsx3 fallback)."""
    try:
        from services.infrastructure.tts import get_tts_recovery, speak_to_bytes

        body = await request.body()
        aspect_id = ""
        speed_override = None
        user_speed = None
        try:
            import json as _j

            data = _j.loads(body)
            text = data.get("text", "")
            aspect_id = str(data.get("aspect_id", "")).strip().lower()
            try:
                _s = data.get("speed")
                if _s is not None:
                    user_speed = max(0.5, min(2.0, float(_s)))
            except (TypeError, ValueError):
                user_speed = None
        except Exception:
            text = body.decode("utf-8", errors="replace").strip()
        if not text:
            return JSONResponse({"ok": False, "error": "No text provided"}, status_code=400)
        # Speech-cleaning floor: /voice/speak speaks whatever a caller posts. Strip reasoning traces +
        # a leading speaker label (NON-destructive), then project markdown → plain text. Deliberately
        # NOT the full strip_junk_from_reply — its model-reply truncation heuristics (cut at
        # "Objective:", "[TOOL", "## SYSTEM") silently chopped a direct caller's benign text
        # ("My main objective: …" → "My main"). In-app callers already post server-cleaned reply text.
        try:
            from services.agent.response_builder import _STREAM_ALLCAPS_MARKER_RE as _acm_voice
            from services.agent.response_builder import _STREAM_MARKER_RE as _sm_voice
            from services.agent.response_builder import _strip_leading_speaker_label as _sls_voice
            from services.agent.response_builder import _strip_reasoning_traces as _srt_voice
            # Also strip bracketed scaffold markers ("[TOOL: …]", "[OBSERVATION: …]", "[⚔ MORRIGAN]") —
            # NON-destructive of prose, so it avoids the "My main objective:" over-cut that motivated
            # skipping the full strip_junk. Without this the marker was SPOKEN aloud verbatim.
            # Active-aspect gate parity with the visible bubble: a bare 'Echo:' for a NON-active aspect
            # is a definition subject, not a self-label — keep it so the audio matches the bubble. Build
            # the active set from the request aspect_id (empty → strip-all, matching the fast path).
            _va = {"layla"}
            if aspect_id:
                _va.add(aspect_id.lower())
            else:
                _va.update({"morrigan", "nyx", "echo", "eris", "cassandra", "lilith"})
            try:
                from services.agent.response_builder import _known_custom_aspect_names
                _va.update(c.lower() for c in _known_custom_aspect_names())
            except Exception:
                pass
            _mk = _acm_voice.sub("", _sm_voice.sub("", text))
            _ct = _text_for_speech(_sls_voice(_srt_voice(_mk), active_names=_va))
            if _ct.strip():
                text = _ct
        except Exception:
            pass
        # Map aspect → TTS speed (matches TTS_VOICE_STYLES in layla-app.js)
        _ASPECT_SPEEDS = {
            "morrigan": 1.05, "nyx": 0.82, "echo": 0.90,
            "eris": 1.20, "cassandra": 1.15, "lilith": 0.78,
        }
        if aspect_id in _ASPECT_SPEEDS:
            speed_override = _ASPECT_SPEEDS[aspect_id]
        # An explicit user speed (settings slider) wins over the aspect default.
        if user_speed is not None:
            speed_override = user_speed
        wav = await asyncio.to_thread(speak_to_bytes, text, speed_override)
        if wav is None:
            rec = get_tts_recovery()
            return JSONResponse(
                {
                    "ok": False,
                    "error": "TTS not available",
                    # One-click guided install: the permissive [voice] extra is the default; the
                    # GPLv3 kokoro upgrade is surfaced under `install.kokoro` behind an explicit
                    # accept, never bundled by the default path.
                    "install": _install_offer(),
                    "recovery": rec
                    or {
                        "what_failed": "No TTS engine",
                        "next_steps": ["pip install kokoro-onnx soundfile", "or: pip install pyttsx3"],
                    },
                },
                status_code=503,
            )
        return Response(content=wav, media_type="audio/wav")
    except Exception:
        logger.exception("TTS error")
        return JSONResponse({"ok": False, "error": "Speech synthesis failed."}, status_code=500)


@router.post("/voice/tts/kokoro/install")
async def voice_install_kokoro(body: dict | None = None):
    """Install the OPT-IN, higher-quality Kokoro neural TTS — GPLv3, so gated on explicit accept.

    kokoro-onnx pulls phonemizer-fork (GPLv3), which pyproject deliberately keeps out of the
    permissive [voice]/[all] extras and scripts/check_copyleft.py FAILS CI on. So it is NEVER
    installed by the default guided path (POST /setup/feature/install feature=voice, which
    installs only faster-whisper + pyttsx3). This endpoint is the one in-app place kokoro can be
    installed, and it REFUSES unless the caller has explicitly accepted GPLv3.

    The package list is HARD-CODED to the two allowlisted kokoro deps — the caller cannot name a
    package — so this maps to the allowlisted installer (install.feature_installer.install_packages),
    never to arbitrary pip. Once the packages land, tts.py prefers kokoro over pyttsx3 on its next
    (re)load automatically; no flag flip is needed, because kokoro is an engine swap inside the
    already-enabled voice feature, not a new capability.
    """
    body = body or {}
    if not bool(body.get("gpl_accept")):
        # Not an error the user did wrong — a required, informed choice. State the licence and
        # exactly how to proceed; do NOT install anything.
        return JSONResponse(
            {
                "ok": False,
                "requires_gpl_accept": True,
                "license": "GPLv3",
                "error": (
                    "Kokoro TTS is GPLv3 (it pulls phonemizer-fork) and is not part of the "
                    "default [voice] install. Re-send with {\"gpl_accept\": true} to accept the "
                    "GPLv3 licence and install it, or run: pip install layla[voice-kokoro]"
                ),
            },
            status_code=200,
        )
    from install.feature_installer import install_packages

    # Hard-coded, allowlisted kokoro deps — never a client-supplied package name.
    res = await asyncio.to_thread(install_packages, ["kokoro-onnx", "soundfile"])
    return JSONResponse(
        {
            "ok": bool(res.get("ok")),
            "engine": "kokoro",
            "installed": res.get("installed", []),
            "failed": res.get("failed", []),
        },
        status_code=200,
    )
