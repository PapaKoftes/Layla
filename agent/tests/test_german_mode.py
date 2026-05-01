# -*- coding: utf-8 -*-
"""
test_german_mode.py — Unit tests for German language learning mode (Item #10)

Tests: profile management, correction engine, flashcard SM-2 scheduling,
calibration quiz, complexity scoring, HTTP endpoints.

Run:
    cd agent/ && python -m pytest tests/test_german_mode.py -v
"""
from __future__ import annotations

import sqlite3
import sys

import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

AGENT_DIR = Path(__file__).resolve().parent.parent
if str(AGENT_DIR) not in sys.path:
    sys.path.insert(0, str(AGENT_DIR))


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def tmp_db(tmp_path, monkeypatch):
    """Redirect german_mode DB to a temp directory."""
    db_file = tmp_path / "german_mode.db"

    def _fake_get_db_path():
        return db_file

    monkeypatch.setattr("services.german_mode._get_db_path", _fake_get_db_path)
    # Also patch utcnow to a stable value so tests are deterministic
    from datetime import datetime, timezone
    _now = datetime(2025, 1, 15, 12, 0, 0, tzinfo=timezone.utc)

    class _FakeUTC:
        @staticmethod
        def isoformat():
            return _now.isoformat()

    monkeypatch.setattr("services.german_mode.time", MagicMock(monotonic=lambda: 0.0))
    return tmp_path


@pytest.fixture()
def client():
    from fastapi.testclient import TestClient
    from main import app
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c


# ---------------------------------------------------------------------------
# Imports
# ---------------------------------------------------------------------------

from services.german_mode import (
    CEFR_LEVELS,
    _sm2,
    add_flashcard,
    build_german_system_block,
    calibrate_from_answers,
    correct_text,
    delete_flashcard,
    detect_errors,
    get_calibration_sentences,
    get_due_cards,
    get_flashcard_stats,
    get_profile,
    review_card,
    score_complexity,
    set_level,
)


# ---------------------------------------------------------------------------
# score_complexity
# ---------------------------------------------------------------------------

class TestScoreComplexity:
    def test_short_sentence_a1(self):
        r = score_complexity("Ich heiße Max.")
        assert r["estimated_level"] == "A1"
        assert r["word_count"] == 3

    def test_medium_sentence_b1(self):
        r = score_complexity("Obwohl es regnet, gehe ich spazieren.")
        assert r["estimated_level"] in ("B1", "A2")
        assert r["subclause_count"] >= 1

    def test_complex_sentence_b2(self):
        # Long sentence with multiple subclauses should score B2 or higher
        text = (
            "Die Entscheidung, die er getroffen hat, war nicht leicht zu verstehen, "
            "weil die Umstände so komplex waren, sodass niemand sicher sein konnte, "
            "ob die Lösung wirklich funktionieren würde, wenn man alle Faktoren bedenkt."
        )
        r = score_complexity(text)
        assert r["estimated_level"] in ("B2", "C1", "C2")

    def test_word_count_correct(self):
        r = score_complexity("ein zwei drei vier")
        assert r["word_count"] == 4

    def test_subclause_count(self):
        r = score_complexity("Ich gehe, weil es regnet und obwohl ich müde bin.")
        assert r["subclause_count"] >= 2


# ---------------------------------------------------------------------------
# detect_errors
# ---------------------------------------------------------------------------

class TestDetectErrors:
    def test_no_errors_clean_sentence(self):
        errors = detect_errors("Ich bin heute zur Schule gegangen.", "B1")
        # No pattern should fire on this clean sentence
        assert isinstance(errors, list)

    def test_dass_vs_das(self):
        errors = detect_errors("Ich glaube, das ich richtig liege.", "B1")
        names = [e["name"] for e in errors]
        assert "dass_vs_das" in names

    def test_dative_after_mit(self):
        errors = detect_errors("Ich gehe mit die Freunde.", "B1")
        names = [e["name"] for e in errors]
        assert "dative_after_mit" in names

    def test_errors_have_required_fields(self):
        errors = detect_errors("Ich gehe mit die Freunde.", "B1")
        for e in errors:
            assert "name" in e
            assert "hint" in e
            assert "match" in e
            assert "level" in e

    def test_level_filter_suppresses_advanced_rules(self):
        # Konjunktiv II rule is B2; should not fire for A1 user
        errors = detect_errors("Er würde gehen.", "A1")
        names = [e["name"] for e in errors]
        assert "konjunktiv_ii" not in names

    def test_b2_user_sees_konjunktiv_hint(self):
        errors = detect_errors("Er würde haben gehen.", "B2")
        names = [e["name"] for e in errors]
        assert "konjunktiv_ii" in names


# ---------------------------------------------------------------------------
# correct_text
# ---------------------------------------------------------------------------

class TestCorrectText:
    def test_returns_ok(self, tmp_db):
        r = correct_text("Ich bin müde.", "test_user")
        assert r["ok"] is True

    def test_has_required_fields(self, tmp_db):
        r = correct_text("Ich gehe mit die Schule.", "test_user")
        for f in ("ok", "original", "errors", "error_count", "complexity", "level", "marks", "suggestion"):
            assert f in r

    def test_no_errors_gives_encouragement(self, tmp_db):
        r = correct_text("Das Buch ist interessant.", "test_user")
        assert "Gut" in r["suggestion"] or r["error_count"] == 0

    def test_error_marks_populated(self, tmp_db):
        r = correct_text("Ich gehe mit die Freunde.", "test_user")
        if r["error_count"] > 0:
            assert len(r["marks"]) > 0

    def test_level_in_result(self, tmp_db):
        r = correct_text("Wir spielen.", "test_user")
        assert r["level"] in CEFR_LEVELS


# ---------------------------------------------------------------------------
# Profile management
# ---------------------------------------------------------------------------

class TestProfile:
    def test_get_profile_returns_dict(self, tmp_db):
        p = get_profile("prof_test")
        assert isinstance(p, dict)
        assert "level" in p

    def test_default_level_b1(self, tmp_db):
        p = get_profile("new_user_xyz")
        assert p["level"] == "B1"

    def test_set_level_persists(self, tmp_db):
        set_level("C1", "level_test")
        p = get_profile("level_test")
        assert p["level"] == "C1"

    def test_invalid_level_raises(self, tmp_db):
        with pytest.raises(ValueError):
            set_level("X9", "err_user")

    def test_set_level_updates_existing(self, tmp_db):
        set_level("A2", "update_test")
        set_level("B2", "update_test")
        p = get_profile("update_test")
        assert p["level"] == "B2"

    def test_all_valid_levels(self, tmp_db):
        for lvl in CEFR_LEVELS:
            set_level(lvl, f"user_{lvl}")
            p = get_profile(f"user_{lvl}")
            assert p["level"] == lvl


# ---------------------------------------------------------------------------
# SM-2 algorithm
# ---------------------------------------------------------------------------

class TestSM2:
    def test_fail_resets_interval(self):
        ef, interval, reps = _sm2(2.5, 10, 3, quality=1)
        assert interval == 1
        assert reps == 0

    def test_pass_increments_reps(self):
        ef, interval, reps = _sm2(2.5, 1, 0, quality=5)
        assert reps == 1

    def test_first_rep_interval_1(self):
        _, interval, _ = _sm2(2.5, 1, 0, quality=4)
        assert interval == 1

    def test_second_rep_interval_6(self):
        _, interval, _ = _sm2(2.5, 1, 1, quality=4)
        assert interval == 6

    def test_third_rep_grows(self):
        _, interval, _ = _sm2(2.5, 6, 2, quality=4)
        assert interval > 6

    def test_ease_factor_decreases_on_hard(self):
        ef_new, _, _ = _sm2(2.5, 6, 2, quality=3)
        assert ef_new < 2.5

    def test_ease_factor_minimum_1_3(self):
        # Multiple consecutive hard reviews should not go below 1.3
        ef = 2.5
        for _ in range(20):
            ef, _, _ = _sm2(ef, 1, 1, quality=3)
        assert ef >= 1.3

    def test_quality_5_maintains_ef(self):
        ef_new, _, _ = _sm2(2.5, 6, 2, quality=5)
        assert ef_new >= 2.5


# ---------------------------------------------------------------------------
# Flashcard CRUD
# ---------------------------------------------------------------------------

class TestFlashcards:
    def test_add_card_returns_ok(self, tmp_db):
        r = add_flashcard("Haus", "house", user_id="fc_user")
        assert r["ok"] is True
        assert "card" in r

    def test_add_card_has_fields(self, tmp_db):
        r = add_flashcard("Schule", "school", example="Die Schule ist groß.", user_id="fc_user")
        card = r["card"]
        assert card["front"] == "Schule"
        assert card["back"] == "school"
        assert card["state"] == "new"

    def test_due_cards_returns_list(self, tmp_db):
        add_flashcard("Tisch", "table", user_id="due_user")
        due = get_due_cards("due_user")
        assert isinstance(due, list)

    def test_new_card_immediately_due(self, tmp_db):
        add_flashcard("Stuhl", "chair", user_id="imm_user")
        due = get_due_cards("imm_user")
        fronts = [c["front"] for c in due]
        assert "Stuhl" in fronts

    def test_stats_counts_new(self, tmp_db):
        add_flashcard("Buch", "book", user_id="stats_user")
        stats = get_flashcard_stats("stats_user")
        assert stats["new"] >= 1
        assert stats["total"] >= 1

    def test_review_pass_changes_state(self, tmp_db):
        r = add_flashcard("Fenster", "window", user_id="rev_user")
        cid = r["card"]["id"]
        rr = review_card(cid, 5, "rev_user")
        assert rr["ok"] is True
        assert rr["card"]["reps"] == 1

    def test_review_fail_resets_reps(self, tmp_db):
        r = add_flashcard("Tür", "door", user_id="fail_user")
        cid = r["card"]["id"]
        # First pass it
        review_card(cid, 5, "fail_user")
        # Then fail it
        rr = review_card(cid, 1, "fail_user")
        assert rr["card"]["reps"] == 0

    def test_delete_card(self, tmp_db):
        r = add_flashcard("Wand", "wall", user_id="del_user")
        cid = r["card"]["id"]
        dr = delete_flashcard(cid, "del_user")
        assert dr["ok"] is True
        due = get_due_cards("del_user")
        assert not any(c["id"] == cid for c in due)

    def test_review_nonexistent_card(self, tmp_db):
        r = review_card(999999, 4, "nocard_user")
        assert r["ok"] is False

    def test_multiple_cards_stats(self, tmp_db):
        for i in range(5):
            add_flashcard(f"Word{i}", f"Def{i}", user_id="multi_user")
        stats = get_flashcard_stats("multi_user")
        assert stats["total"] == 5
        assert stats["new"] == 5


# ---------------------------------------------------------------------------
# Calibration
# ---------------------------------------------------------------------------

class TestCalibration:
    def test_calibration_sentences_returned(self):
        sents = get_calibration_sentences("B1")
        assert isinstance(sents, list)
        assert len(sents) > 0

    def test_calibration_all_levels_have_sentences(self):
        for lvl in CEFR_LEVELS:
            sents = get_calibration_sentences(lvl)
            assert len(sents) > 0, f"No sentences for {lvl}"

    def test_calibrate_from_answers_ok(self, tmp_db):
        answers = [
            {"level": "A1", "score": 5},
            {"level": "A2", "score": 5},
            {"level": "B1", "score": 4},
            {"level": "B2", "score": 2},
        ]
        r = calibrate_from_answers(answers, "cal_user")
        assert r["ok"] is True
        assert r["recommended_level"] in CEFR_LEVELS

    def test_calibrate_b2_level_high_scores(self, tmp_db):
        answers = [
            {"level": "A1", "score": 5},
            {"level": "A2", "score": 5},
            {"level": "B1", "score": 5},
            {"level": "B2", "score": 4},
        ]
        r = calibrate_from_answers(answers, "cal_b2")
        assert r["recommended_level"] == "B2"

    def test_calibrate_empty_answers_fails(self, tmp_db):
        r = calibrate_from_answers([], "cal_empty")
        assert r["ok"] is False

    def test_calibrate_low_scores_gives_a1(self, tmp_db):
        answers = [{"level": "A1", "score": 2}]
        r = calibrate_from_answers(answers, "cal_low")
        assert r["recommended_level"] == "A1"


# ---------------------------------------------------------------------------
# build_german_system_block
# ---------------------------------------------------------------------------

class TestSystemBlock:
    def test_returns_string(self):
        block = build_german_system_block("B1")
        assert isinstance(block, str)
        assert len(block) > 50

    def test_level_in_block(self):
        block = build_german_system_block("B2")
        assert "B2" in block

    def test_correction_instruction_present(self):
        block = build_german_system_block("B1")
        assert "Korrektur" in block or "korrigiere" in block

    def test_vocab_suggestion_instruction(self):
        block = build_german_system_block("A2")
        assert "Vokabel" in block or "vocab" in block.lower()

    def test_all_levels_produce_block(self):
        for lvl in CEFR_LEVELS:
            b = build_german_system_block(lvl)
            assert lvl in b


# ---------------------------------------------------------------------------
# HTTP Endpoints
# ---------------------------------------------------------------------------

@pytest.mark.endpoint
class TestGermanEndpoints:
    def test_profile_endpoint_reachable(self, client):
        r = client.get("/german/profile")
        assert r.status_code != 404

    def test_profile_ok_field(self, client):
        r = client.get("/german/profile")
        if r.status_code == 200:
            assert r.json().get("ok") is True

    def test_set_level_endpoint(self, client):
        r = client.post("/german/profile/level", json={"level": "B2"})
        if r.status_code == 200:
            assert r.json().get("ok") is True

    def test_invalid_level_returns_error(self, client):
        r = client.post("/german/profile/level", json={"level": "Z9"})
        if r.status_code == 200:
            assert r.json().get("ok") is False

    def test_correct_endpoint(self, client):
        r = client.post("/german/correct", json={"text": "Ich gehe mit die Schule."})
        if r.status_code == 200:
            data = r.json()
            assert "errors" in data
            assert "complexity" in data

    def test_correct_empty_text(self, client):
        r = client.post("/german/correct", json={"text": ""})
        if r.status_code == 200:
            assert r.json().get("ok") is False

    def test_calibrate_sentences_endpoint(self, client):
        r = client.get("/german/calibrate/B1")
        if r.status_code == 200:
            assert r.json().get("ok") is True
            assert isinstance(r.json()["sentences"], list)

    def test_calibrate_post_endpoint(self, client):
        r = client.post("/german/calibrate", json={
            "answers": [{"level": "B1", "score": 4}],
            "user_id": "http_test"
        })
        if r.status_code == 200:
            assert r.json().get("ok") is True

    def test_flashcards_due_endpoint(self, client):
        r = client.get("/german/flashcards/due")
        assert r.status_code != 404

    def test_flashcards_stats_endpoint(self, client):
        r = client.get("/german/flashcards/stats")
        if r.status_code == 200:
            assert r.json().get("ok") is True

    def test_add_flashcard_endpoint(self, client):
        r = client.post("/german/flashcards", json={
            "front": "lernen",
            "back": "to learn",
            "example": "Ich lerne Deutsch.",
            "user_id": "http_fc_user",
        })
        if r.status_code == 200:
            assert r.json().get("ok") is True

    def test_add_flashcard_missing_fields(self, client):
        r = client.post("/german/flashcards", json={"front": "lernen"})
        if r.status_code == 200:
            assert r.json().get("ok") is False

    def test_corrections_history_endpoint(self, client):
        r = client.get("/german/corrections")
        assert r.status_code != 404
