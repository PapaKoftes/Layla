from services.personality.operator_quiz import get_stage, score_answers


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
    """Unrecognised answers score nothing — and "nothing" now means nothing is STORED either.

    This used to assert `kv["stat_technical"] == "5"`, i.e. that two junk answers still persisted
    all six stats at the neutral seed. That is what the seed is: a display baseline, not an
    answer. Storing it made `familiarity.PROFILE_ROSTER` count six things the operator never
    said — see tests/test_familiarity_is_honest.py, where a no-answer run scored 11 of 23.
    The preview keeps all six so the UI can still render every slider.
    """
    preview, kv = score_answers(
        [
            {"question_id": "does_not_exist", "option_id": "x"},
            {"question_id": "bug_2am", "option_id": "also_nope"},
        ]
    )
    assert preview["stats"]["technical"] == 5
    assert not [k for k in kv if k.startswith("stat_")], (
        f"answers that scored nothing still persisted stats: {kv}"
    )


def test_quiz_scoring_preserves_stats_already_on_file():
    """A rerun that scores nothing must not ERASE a real answer from an earlier session."""
    preview, kv = score_answers([], seed_identity={"stat_technical": "9"})
    assert preview["stats"]["technical"] == 9
    assert kv["stat_technical"] == "9"

