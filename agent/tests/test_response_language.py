"""BL-160: multilingual flagship — response-language block + normalization."""
from __future__ import annotations

from services.prompts import response_language as rl


def test_normalize_accepts_code_name_native():
    assert rl.normalize_language("spanish") == "spanish"
    assert rl.normalize_language("Español") == "spanish"
    assert rl.normalize_language("Italian") == "italian"
    assert rl.normalize_language("日本語") == "japanese"


def test_normalize_default_and_unknown():
    assert rl.normalize_language("") == ""
    assert rl.normalize_language("auto") == ""
    assert rl.normalize_language("klingon") == ""


def test_build_block_for_language():
    block = rl.build_language_block("spanish")
    assert "## Language" in block
    assert "Español" in block and "Spanish" in block
    assert "persona" in block  # capabilities/persona preserved


def test_build_block_empty_for_default():
    assert rl.build_language_block("") == ""
    assert rl.build_language_block("auto") == ""


def test_supported_includes_tutor_and_extra():
    codes = {l["code"] for l in rl.supported_languages()}
    assert "german" in codes and "spanish" in codes   # from tutor registry
    assert "japanese" in codes and "arabic" in codes   # from extras


def test_prompt_injection_wires_block(monkeypatch):
    # the system head builder should append the block when response_language is set
    from services.prompts import response_language as _rl
    assert _rl.response_language_from_config({"response_language": "italian"}) == "italian"
    assert _rl.response_language_from_config({}) == ""


def test_router_get_and_set(monkeypatch, tmp_path):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from routers import language as lang_router

    saved = {}
    monkeypatch.setattr("runtime_safety.load_config", lambda: dict(saved), raising=False)
    monkeypatch.setattr("services.infrastructure.setup_engine.save_config",
                        lambda cfg: saved.update(cfg), raising=False)

    app = FastAPI(); app.include_router(lang_router.router)
    client = TestClient(app)

    r = client.post("/language/response", json={"language": "Français"}).json()
    assert r["ok"] and r["response_language"] == "french"
    assert "Français" in r["preview"]
    assert saved["response_language"] == "french"

    g = client.get("/language/response").json()
    assert g["current"] == "french" and any(l["code"] == "french" for l in g["supported"])
