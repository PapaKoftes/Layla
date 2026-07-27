"""
Voice (TTS/STT) — installable + wired, with the GPL question resolved.

PLAN ITEM 16. Voice engines are a ~500 MB opt-in, so they ship OFF and /voice/* answers 503 until
installed. This slice turns that 503 into a ONE-CLICK GUIDED INSTALL and wires the engines behind
the existing toggles once present. The licensing split is already settled in pyproject +
scripts/check_copyleft.py and is NOT re-litigated here — these tests only hold it in place:

  * the DEFAULT install offer is the permissive `voice` feature (faster-whisper MIT + pyttsx3);
  * kokoro-onnx (GPLv3, via phonemizer-fork) is a SEPARATE opt-in, never in the default path,
    and only installable after an explicit {"gpl_accept": true}.

NOTHING here runs a real pip install or hits the network: the engines are stubbed and the installer
is monkeypatched. What is proven is the WIRING and the HONESTY, not that a box then speaks.

The four contracts (mirroring the plan's test checklist):
  (a) /voice/* 503 carries an actionable install descriptor mapping to an ALLOWLISTED feature id
      (never arbitrary pip);
  (b) the permissive [voice] path is the default; kokoro requires the explicit GPL-accept opt-in;
  (c) with the engine mocked-present, speak/listen return success (wiring proven);
  (d) never-installed degrades to the clear 503, no crash (no 500).
"""
from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from routers import voice as voice_router

_app = FastAPI()
_app.include_router(voice_router.router)
client = TestClient(_app)

# A tiny non-empty audio payload — the route rejects an empty body with 400 before it ever
# reaches the STT engine, so the 503/200 paths need *something* here.
_AUDIO = b"\x00\x01\x02\x03fake-webm-bytes"


# ── (a) the 503 carries an actionable install descriptor → an allowlisted feature id ──────────────

def _force_stt_absent(monkeypatch):
    import services.infrastructure.stt as stt
    monkeypatch.setattr(stt, "is_stt_ready", lambda: False)
    monkeypatch.setattr(stt, "get_stt_recovery", lambda: None)


def _force_tts_absent(monkeypatch):
    import services.infrastructure.tts as tts
    monkeypatch.setattr(tts, "speak_to_bytes", lambda text, speed=None: None)
    monkeypatch.setattr(tts, "get_tts_recovery", lambda: None)


def test_transcribe_503_carries_the_install_descriptor(monkeypatch):
    _force_stt_absent(monkeypatch)
    r = client.post("/voice/transcribe", content=_AUDIO)
    assert r.status_code == 503
    offer = r.json().get("install")
    assert offer, "the 503 must carry an actionable install descriptor, not just a recovery blob"
    assert offer["feature_id"] == "voice"
    assert offer["endpoint"] == "/setup/feature/install", "must reuse the existing feature-install endpoint"


def test_speak_503_carries_the_install_descriptor(monkeypatch):
    _force_tts_absent(monkeypatch)
    r = client.post("/voice/speak", json={"text": "hello"})
    assert r.status_code == 503
    offer = r.json().get("install")
    assert offer and offer["feature_id"] == "voice"


def test_descriptor_maps_to_a_real_feature_id_and_allowlisted_packages_not_arbitrary_pip():
    """The whole security point: the one-click maps to an ALLOWLISTED feature/packages, so a
    compromised client cannot turn 'install voice' into 'pip install anything'."""
    from install.feature_status import voice_install_descriptor
    from install.setup_profiles import feature_by_id
    from services.infrastructure.dependency_recovery import is_pip_allowlisted

    offer = voice_install_descriptor()
    assert feature_by_id(offer["feature_id"]) is not None, "feature_id must be a real FEATURE_MANIFEST id"
    assert offer["installs"], "the descriptor must say what it installs"
    for pkg in offer["installs"]:
        assert is_pip_allowlisted(pkg), f"{pkg!r} in the default offer is not on the pip allowlist"


# ── (b) permissive [voice] is the default; kokoro is GPL-opt-in only ──────────────────────────────

def test_default_offer_is_permissive_and_excludes_kokoro():
    from install.feature_status import voice_install_descriptor

    offer = voice_install_descriptor()
    assert offer["default"] is True
    assert "kokoro-onnx" not in offer["installs"], "kokoro (GPLv3) must NEVER be in the default path"
    assert "faster-whisper" in offer["installs"] and "pyttsx3" in offer["installs"]
    assert "permissive" in offer["license"].lower()


def test_kokoro_is_surfaced_but_gated_behind_explicit_gpl_accept():
    from install.feature_status import voice_install_descriptor
    from services.infrastructure.dependency_recovery import is_pip_allowlisted

    kokoro = voice_install_descriptor()["kokoro"]
    assert kokoro["requires_gpl_accept"] is True
    assert kokoro["default"] is False
    assert "gpl" in kokoro["license"].lower()
    # Its packages are allowlisted (so the gated one-click is not arbitrary pip either) —
    # they are simply never offered by the default path.
    for pkg in kokoro["installs"]:
        assert is_pip_allowlisted(pkg)


def test_kokoro_install_refuses_without_gpl_accept(monkeypatch):
    """No accept → no install. The installer must not even be reached."""
    import install.feature_installer as fi

    def _boom(*a, **k):
        raise AssertionError("install_packages must not run without an explicit GPLv3 accept")

    monkeypatch.setattr(fi, "install_packages", _boom)
    d = client.post("/voice/tts/kokoro/install", json={}).json()
    assert d["ok"] is False
    assert d["requires_gpl_accept"] is True
    assert d["license"] == "GPLv3"


def test_kokoro_install_runs_only_hardcoded_allowlisted_packages_on_accept(monkeypatch):
    """With the accept, kokoro installs — and ONLY the two hard-coded allowlisted deps, never a
    package name the client tried to smuggle in."""
    import install.feature_installer as fi

    seen = {}

    def _fake_install(pkgs, **kw):
        seen["pkgs"] = list(pkgs)
        return {"ok": True, "installed": list(pkgs), "failed": []}

    monkeypatch.setattr(fi, "install_packages", _fake_install)
    d = client.post(
        "/voice/tts/kokoro/install",
        json={"gpl_accept": True, "packages": ["evil-arbitrary-pkg"]},  # the smuggle attempt
    ).json()
    assert d["ok"] is True and d["engine"] == "kokoro"
    assert seen["pkgs"] == ["kokoro-onnx", "soundfile"], "must ignore client packages; hard-coded only"


# ── (c) engine mocked-present → speak/listen actually work (wiring proven) ────────────────────────

def test_transcribe_returns_text_when_the_engine_is_present(monkeypatch):
    import services.infrastructure.stt as stt

    monkeypatch.setattr(stt, "is_stt_ready", lambda: True)
    monkeypatch.setattr(stt, "transcribe_bytes", lambda audio, language=None: "hello world")
    r = client.post("/voice/transcribe", content=_AUDIO)
    assert r.status_code == 200
    assert r.json() == {"ok": True, "text": "hello world"}


def test_speak_returns_wav_when_the_engine_is_present(monkeypatch):
    import services.infrastructure.tts as tts

    wav = b"RIFF____WAVEfmt " + b"\x00" * 64
    monkeypatch.setattr(tts, "speak_to_bytes", lambda text, speed=None: wav)
    r = client.post("/voice/speak", json={"text": "Layla here."})
    assert r.status_code == 200
    assert r.headers["content-type"] == "audio/wav"
    assert r.content == wav


# ── (d) never-installed degrades to a clear 503, no crash ─────────────────────────────────────────

def test_never_installed_is_a_clean_503_not_a_500(monkeypatch):
    _force_stt_absent(monkeypatch)
    _force_tts_absent(monkeypatch)

    rt = client.post("/voice/transcribe", content=_AUDIO)
    assert rt.status_code == 503 and rt.json()["ok"] is False

    rs = client.post("/voice/speak", json={"text": "hi"})
    assert rs.status_code == 503 and rs.json()["ok"] is False


def test_empty_body_is_a_400_not_a_crash():
    """Guard the pre-engine validation path stays intact (a 500 here would mask the 503 story)."""
    r = client.post("/voice/transcribe", content=b"")
    assert r.status_code == 400
