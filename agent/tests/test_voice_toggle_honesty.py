"""BL-270/271/272: the "Speak replies" toggle must not claim a capability this machine does not have.

MEASURED ON THIS BOX (not assumed — every one verified before the fix):
    .venv:  kokoro_onnx MISSING · pyttsx3 MISSING · soundfile MISSING · onnxruntime MISSING
            faster_whisper MISSING
    live GET /health/deps -> {"voice_stt":"missing","voice_tts":"missing",...}
    POST /voice/speak -> 503

So server TTS is 100% dead, and what the operator actually heard was an undocumented browser
speechSynthesis fallback: a generic OS voice, cut at 500 chars, with the speed/volume sliders applying
ONLY to the dead server path. The fallback is what hid the whole thing — it spoke, so nothing looked
broken.

THREE DEFECTS, all fixed here:
  (a) BL-270  speakText gated on a MODULE-LOCAL `_ttsEnabled` written once at import, with no exported
              setter. main.js::toggleTts could only reach the window mirror, so ticking the box did
              NOTHING until a page reload. Invisible because the callers check the fresh mirror and then
              call speakText, which bails on the stale local.
  (b) BL-271  voice.js read `=== 'true'` (unset -> OFF); obsidian.js read `!== 'false'` (unset -> ON).
              A fresh profile rendered the box CHECKED over a disabled engine.
  (c) BL-272  the toggle was never gated on real availability, though /health/deps already reported it
              and had zero UI consumers.

WHY GATED AND NOT DELETED. The operator's runtime_config.json lists "voice" in setup_features (profile
"power") — voice was explicitly chosen; it is missing because auto_pip_install_optional=false, not
because nobody wanted it. Deleting the toggle would strand anyone who installs the feature with no way
to switch it on. /setup/feature/install exists and installs deps ["faster-whisper","kokoro-onnx"].

These are source-contract tests over ES modules — this repo has no JS test runner (no bundler, no npm),
so they assert the wiring rather than execute it. That is a REAL limit: they prove the setter is called
and the probe exists, NOT that a browser then speaks. Each one fails if its defect is reintroduced,
which is verified by reverting each in turn.
"""
from __future__ import annotations

import re
from pathlib import Path

UI = Path(__file__).resolve().parent.parent / "ui"
VOICE = UI / "components" / "voice.js"
MAIN = UI / "main.js"
OBSIDIAN = UI / "components" / "obsidian.js"
INDEX = UI / "index.html"


def _src(p: Path) -> str:
    return p.read_text(encoding="utf-8", errors="replace")


def _code(p: Path) -> str:
    """Source with `//` comments stripped.

    The first cut of test_one_source_of_truth_for_the_tts_default failed against the FIXED code, because
    the comment explaining the bug quotes the buggy expression verbatim. A guard that cannot tell code
    from prose about code would keep misfiring — or worse, be "fixed" by deleting the explanation.
    """
    out = []
    for line in p.read_text(encoding="utf-8", errors="replace").splitlines():
        s = line.lstrip()
        if s.startswith("//") or s.startswith("*") or s.startswith("/*"):
            continue
        out.append(re.sub(r"\s+//\s.*$", "", line))
    return "\n".join(out)


# ── (a) BL-270: the toggle must actually reach the module-local ───────────────────────────────────────

def test_voice_exports_a_tts_setter():
    """Without an exported setter, the module-local can only ever be written at import time."""
    assert re.search(r"export function setTtsEnabled\s*\(", _src(VOICE)), (
        "voice.js must export setTtsEnabled — speakText gates on the module-local `_ttsEnabled`, and "
        "with no setter the toggle cannot change it (BL-270)."
    )


def test_the_setter_writes_local_mirror_and_storage_together():
    body = _src(VOICE).split("export function setTtsEnabled")[1].split("\n}")[0]
    assert "_ttsEnabled =" in body, "must write the module-local — the whole point"
    assert "window._ttsEnabled" in body, "must keep the mirror app.js/research.js read"
    assert "setItem" in body, "must persist the preference"


def test_toggle_handler_goes_through_the_setter():
    """main.js::toggleTts setting only the mirror IS the bug."""
    handler = _src(MAIN).split("toggleTts:")[1].split("},")[0]
    assert "setTtsEnabled" in handler, (
        "toggleTts must call voice.setTtsEnabled. Writing window._ttsEnabled directly leaves the "
        "module-local stale and the toggle silently no-ops until reload (BL-270)."
    )
    assert not re.search(r"window\._ttsEnabled\s*=\s*checked", handler), (
        "the raw mirror write is the defect itself"
    )


# ── (b) BL-271: one default, not two ──────────────────────────────────────────────────────────────────

def test_one_source_of_truth_for_the_tts_default():
    assert "export function readTtsPref" in _src(VOICE)
    obs_code = _code(OBSIDIAN)  # comments stripped: the fix's comment quotes the buggy expression
    assert "readTtsPref" in obs_code, "obsidian.js must use the shared reader, not its own comparison"
    assert "layla_tts" not in obs_code, (
        "obsidian.js must not read the layla_tts key directly. It used `!== 'false'` (unset -> ON) while "
        "voice.js used `=== 'true'` (unset -> OFF), so a fresh profile rendered the box CHECKED over a "
        "disabled engine (BL-271). One reader, or they drift again."
    )


def test_default_is_off_when_unset():
    """Unexpected speech is a nasty surprise; opt-in is the correct default."""
    body = _src(VOICE).split("export function readTtsPref")[1].split("\n}")[0]
    assert "=== 'true'" in body, "unset must mean OFF"


# ── (c) BL-272: gate on measured availability ─────────────────────────────────────────────────────────

def test_availability_is_probed_from_health_deps():
    src = _src(VOICE)
    assert "refreshVoiceAvailability" in src
    probe = src.split("export async function refreshVoiceAvailability")[1].split("\n}")[0]
    assert "/health/deps" in probe, (
        "availability must come from /health/deps — it already exists, already works, and had zero UI "
        "consumers while the UI claimed voice worked (BL-272)."
    )
    assert "voice_tts" in probe, "must read the voice_tts dependency specifically"


def test_probe_runs_at_init():
    init = _src(VOICE).split("export function initVoiceControls")[1]
    assert "refreshVoiceAvailability()" in init, "a probe nobody calls changes nothing"


def test_unavailable_disables_the_toggle_and_explains():
    src = _src(VOICE)
    assert "cb.disabled = !available" in src, "the toggle must be DISABLED when the engine is missing"
    assert "isn't installed" in src, "must say WHY rather than silently going dead"
    assert re.search(r"voice-speed-range|voice-volume-range", src), (
        "the speed/volume sliders drive the server path only — they must be disabled too, or they are "
        "still lying"
    )


def test_probe_failure_is_treated_as_unavailable():
    """A failed probe must not be read as 'installed'. Fail closed."""
    probe = _src(VOICE).split("export async function refreshVoiceAvailability")[1].split("\n}")[0]
    assert re.search(r"catch\s*\(_e\)\s*\{\s*ok\s*=\s*false", probe), (
        "an unreachable /health/deps must mean 'cannot confirm' -> unavailable"
    )


def test_no_silent_browser_fallback_when_engine_is_absent():
    """The undocumented speechSynthesis fallback is what made the dead toggle look alive."""
    body = _src(VOICE).split("export async function speakText")[1].split("\nexport ")[0]
    assert "_ttsAvailable === false" in body, (
        "speakText must refuse when TTS is known-absent, instead of quietly substituting a generic OS "
        "voice with dead speed/volume sliders and a 500-char cut (BL-272)."
    )


def test_the_notes_and_rows_the_js_targets_exist():
    """Same class of defect as BL-335: JS reaching for elements that were never added."""
    html = _src(INDEX)
    for gid in ("tts-note", "tts-note2", "tts-toggle-row", "tts-toggle2-row"):
        assert f'id="{gid}"' in html, f"#{gid} must exist — voice.js writes to it"
