from services.operator_quiz import get_stage, score_answers


def test_quiz_stage_exists():
    d = get_stage(0)
    assert d["ok"] is True
    assert d["stage"] == 0
    assert isinstance(d["questions"], list)
    assert d["questions"]


def test_quiz_scoring_clamps_stats():
    # Spam a single option to try to push beyond bounds; scoring must clamp to 1..10
    answers = [{"question_id": "bug_2am", "option_id": "fix_now"} for _ in range(50)]
    preview, kv = score_answers(answers, seed_identity=None)
    stats = preview["stats"]
    assert 1 <= stats["technical"] <= 10
    assert 1 <= stats["ambition"] <= 10
    # Ensure keys are emitted for storage
    assert "stat_technical" in kv
    assert "maturity_phase" in kv


def test_quiz_scoring_ignores_unknown_items():
    preview, kv = score_answers(
        [
            {"question_id": "does_not_exist", "option_id": "x"},
            {"question_id": "bug_2am", "option_id": "also_nope"},
        ]
    )
    assert preview["stats"]["technical"] == 5
    assert kv["stat_technical"] == "5"

