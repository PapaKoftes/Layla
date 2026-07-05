"""BL-220: generalized multi-language tutor — any language via LLM correction + per-lang SRS/level."""
from __future__ import annotations

from services.infrastructure import language_tutor as lt


def test_language_registry():
    langs = {l["code"] for l in lt.list_languages()}
    assert {"german", "italian", "spanish"} <= langs
    assert lt.normalize_language("ITALIAN") == "italian"
    assert lt.normalize_language("klingon") == "german"  # unknown → default
    assert lt.language_name("spanish") == "Spanish"


def test_profile_and_level():
    p = lt.get_profile("italian", user_id="u1")
    assert p["level"] == "B1" and p["language"] == "italian" and p["language_name"] == "Italian"
    assert lt.set_level("italian", "B2", user_id="u1")["ok"] is True
    assert lt.get_profile("italian", user_id="u1")["level"] == "B2"
    # per-language: spanish for the same user is independent, still default
    assert lt.get_profile("spanish", user_id="u1")["level"] == "B1"
    assert lt.set_level("italian", "Z9", user_id="u1")["ok"] is False


def test_correct_via_llm(monkeypatch):
    fake = '{"corrected": "Io vado al mare", "errors": [{"match": "va", "hint": "use \'vado\' (1st person)"}]}'
    monkeypatch.setattr(lt, "_llm_complete", lambda prompt: fake)
    r = lt.correct("Io va al mare", "italian", user_id="u2")
    assert r["ok"] is True and r["language"] == "italian"
    assert r["corrected"] == "Io vado al mare"
    assert r["errors"][0]["match"] == "va" and r["correct"] is False
    # prompt carried the language name
    seen = {}
    monkeypatch.setattr(lt, "_llm_complete", lambda prompt: seen.setdefault("p", prompt) or '{"corrected":"x","errors":[]}')
    lt.correct("hola", "spanish", user_id="u2")
    assert "Spanish" in seen["p"]


def test_flashcard_srs():
    add = lt.add_card("spanish", "el gato", "the cat", user_id="u3")
    assert add["ok"] is True
    cid = add["id"]
    due = lt.due_cards("spanish", user_id="u3")
    assert any(c["id"] == cid for c in due["cards"])
    # a good grade pushes the due date out + grows the interval
    r1 = lt.review_card(cid, 5, user_id="u3")
    assert r1["ok"] is True and r1["reps"] == 1
    assert lt.stats("spanish", user_id="u3")["total"] == 1
    # a fail resets
    r2 = lt.review_card(cid, 1, user_id="u3")
    assert r2["reps"] == 0


def test_calibration():
    assert len(lt.calibration_sentences("italian", "A1")) == 3
    assert len(lt.calibration_sentences("spanish", "B1")) >= 1
    rec = lt.calibrate("italian", [{"level": "A1", "score": 5}, {"level": "B1", "score": 4}, {"level": "B2", "score": 1}], user_id="u4")
    assert rec["ok"] is True and rec["recommended_level"] == "B1"


def test_router(monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    monkeypatch.setattr(lt, "_llm_complete", lambda prompt: '{"corrected": "Ich bin gegangen", "errors": []}')
    from routers import language as lr
    app = FastAPI(); app.include_router(lr.router)
    client = TestClient(app)
    assert {l["code"] for l in client.get("/language/languages").json()["languages"]} >= {"german", "italian", "spanish"}
    assert client.get("/language/italian/profile").json()["language"] == "italian"
    r = client.post("/language/german/correct", json={"text": "Ich habe gegangen"}).json()
    assert r["ok"] is True and r["correct"] is True
    cal = client.get("/language/spanish/calibrate/A1").json()
    assert len(cal["sentences"]) == 3
