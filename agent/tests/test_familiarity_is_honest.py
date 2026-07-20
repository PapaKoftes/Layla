"""R3 — the rank/XP badge becomes a MIRROR, and the mirror must not be a relabelled counter.

The brief's hard rule: "DO NOT RELABEL A COUNTER AS INTIMACY." XP is an activity odometer —
`award_xp` is called from 14 sites and every one counts an action (conversation_turn 3,
tool_success 5, plan_executed 20, study_session 20, capability_practice 30, research_mission 50,
daily_activity 5-25, ...). Calling that "how much she has learned about you" would be a fresh lie.

So familiarity is computed from stores that really are about the operator, and these tests pin the
three properties that keep it honest:

  1. It is INDEPENDENT of XP/rank. Award a pile of XP and the familiarity number must not move.
  2. It is AUDITABLE. The headline fraction is recomputable by hand from the rows shown beneath it,
     and every row carries the value actually stored for it.
  3. It EXCLUDES the stores that are not about the operator — chiefly `learnings`, whose real
     contents are world facts and docstring fragments scraped from Layla's own replies.
"""

from __future__ import annotations

import sys
from pathlib import Path

AGENT_DIR = Path(__file__).resolve().parent.parent
if str(AGENT_DIR) not in sys.path:
    sys.path.insert(0, str(AGENT_DIR))


# ── 1. Independent of the activity counter ──────────────────────────────────────

def test_familiarity_does_not_move_when_xp_is_awarded(isolated_db):
    """The whole point. If XP moved this number, it would be the counter wearing a new label."""
    from services.personality import familiarity
    from services.personality.maturity_engine import award_xp, get_state

    before = familiarity.get_familiarity()
    award_xp(5000, reason="test_activity_burst")
    after = familiarity.get_familiarity()

    assert get_state().xp != 0 or get_state().rank > 0, "the XP award did not land; test is vacuous"
    assert (after["known"], after["total"], after["pct"]) == (
        before["known"], before["total"], before["pct"]
    ), "familiarity moved when XP was awarded — it is measuring activity, not knowledge"


def test_familiarity_moves_when_she_actually_learns_something(isolated_db):
    """The positive half. Without it, "does not move" would pass by never moving at all."""
    from layla.memory.db import set_user_identity
    from services.personality import familiarity

    before = familiarity.get_familiarity()
    set_user_identity("name", "Mina")
    set_user_identity("communication_style", "direct")
    after = familiarity.get_familiarity()

    assert after["known"] == before["known"] + 2, (
        f"learned two things about the operator and the count went {before['known']}→{after['known']}"
    )
    assert after["total"] == before["total"], "the denominator moved; the roster must be fixed"


# ── 2. Auditable: the headline is recomputable from the rows ────────────────────

def test_headline_fraction_equals_the_visible_rows(isolated_db):
    """A user must be able to count the ticks and get the headline. No hidden weighting."""
    from services.personality import familiarity

    f = familiarity.get_familiarity()
    assert f["total"] == len(f["answers"]), "denominator is not the number of rows shown"
    assert f["known"] == sum(1 for a in f["answers"] if a["known"]), (
        "numerator is not the number of ticked rows shown"
    )
    assert f["pct"] == int(round(100.0 * f["known"] / f["total"]))


def test_every_row_shows_the_value_it_is_counting(isolated_db):
    """A tick with no visible value is unauditable — the user cannot tell what she thinks she knows."""
    from layla.memory.db import set_user_identity
    from services.personality import familiarity

    set_user_identity("humour_preference", "light")
    row = next(a for a in familiarity.get_familiarity()["answers"] if a["key"] == "humour_preference")
    assert row["known"] is True and row["value"] == "light"


def test_unbounded_counts_stay_out_of_the_fraction(isolated_db):
    """Exchanges/days/adapted-aspects have no maximum. Folding one into a percentage is exactly how
    a counter gets dressed up as intimacy, so they are returned as context and never as roster rows."""
    from services.personality import familiarity

    f = familiarity.get_familiarity()
    context_ids = {c["id"] for c in f["context"]}
    assert {"exchanges", "days", "domains"} <= context_ids
    roster_keys = {a["key"] for a in f["answers"]}
    assert not (context_ids & roster_keys), "a context count leaked into the counted roster"
    for c in f["context"]:
        assert c.get("basis"), f"context row {c['id']!r} does not say where its number comes from"


def test_the_basis_is_published_so_the_number_can_be_checked(isolated_db):
    """"State the basis in the UI so the number is auditable rather than mystical." """
    from services.personality import familiarity

    f = familiarity.get_familiarity()
    assert f["basis"], "no basis text"
    assert f"{f['known']} of {f['total']}" in f["basis"]
    assert f["sources"].get("profile") and f["sources"].get("traits")


# ── 3. Excludes the stores that are not about the operator ──────────────────────

def test_learnings_are_not_counted_as_facts_about_you(isolated_db):
    """On a real DB the 28 `learnings` rows are world facts and docstring fragments re-ingested from
    Layla's own replies ("Paris serves as the political ... center of France", "n (int): The number
    to check for primality"). Counting those as things she knows about the operator is the lie."""
    from layla.memory.learnings import save_learning
    from services.personality import familiarity

    before = familiarity.get_familiarity()
    for text in (
        "Paris serves as the political, cultural, and economic center of France.",
        "Multiplication is a fundamental arithmetic operation.",
        "n (int): The number to check for primality.",
    ):
        save_learning(text, kind="fact")
    after = familiarity.get_familiarity()

    assert after["known"] == before["known"], (
        "saving generic world facts raised 'how well she knows you' — learnings are not about the operator"
    )


def test_roster_keys_are_real_identity_keys_not_invented(isolated_db):
    """The denominator must be things some code path really writes, or the fraction is fiction."""
    import re

    from services.personality.familiarity import PROFILE_ROSTER, TRAIT_LABELS

    sources = [
        p for p in AGENT_DIR.rglob("*.py")
        if "tests" not in p.parts and p.name != "familiarity.py"
    ]
    blob = "\n".join(p.read_text(encoding="utf-8", errors="ignore") for p in sources)

    for key, _label in PROFILE_ROSTER:
        assert re.search(rf'["\']{re.escape(key)}["\']', blob), (
            f"roster key {key!r} is written by nothing outside familiarity.py — it inflates the "
            "denominator with something that can never be known."
        )
    for stat in TRAIT_LABELS:
        assert re.search(rf'["\']{re.escape(stat)}["\']', blob), f"unknown stat {stat!r}"


# ── The operator's live values must render sensibly (rank 2 / 824 XP) ───────────

def test_renders_sensibly_at_the_operators_real_state(isolated_db):
    """Their DB is rank 2 / 824 XP with a completed quiz. Reproduce that shape and check the panel
    payload is coherent — and that nothing here recomputes or migrates their progress."""
    from layla.memory.db import get_all_user_identity, set_user_identity
    from services.personality import familiarity
    from services.personality.maturity_engine import get_state

    set_user_identity("maturity_xp", "824")
    set_user_identity("maturity_rank", "2")
    set_user_identity("maturity_phase", "awakening")
    for k, v in (
        ("name", "Mina"), ("communication_style", "direct"), ("formality_level", "casual"),
        ("humour_preference", "light"), ("assistant_style", "concise"),
        ("stat_technical", "10"), ("stat_creative", "7"),
    ):
        set_user_identity(k, v)

    f = familiarity.get_familiarity()
    assert f["ok"] and f["known"] == 7 and 0 < f["pct"] < 100
    # Untouched: reading familiarity must not rewrite maturity.
    st = get_state()
    assert (st.xp, st.rank) == (824, 2), "reading familiarity changed the operator's progress"
    assert get_all_user_identity()["maturity_xp"] == "824"


# ── 4. It counts what the OPERATOR said, not what the program wrote ─────────────
# THE INDICATOR MUST NOT BE INFLATED BY ITS OWN DEFAULTS. `_roster` ticks a row whenever the
# stored value is non-empty, and two code paths used to store values nobody supplied:
# `onboarding_interview._apply_personality_prefs` wrote formality_level / humour_preference /
# proactivity_level / preferred_response_length from hardcoded fallbacks and watch_folders from a
# catch-all `else`, and `operator_quiz.score_answers` persisted all six stat_* at the neutral seed
# 5 even for a submission with zero answers. A user who answered NOTHING scored 11 of 23 — 48%
# "how well she knows you" — in the one module whose entire purpose is to stop overclaiming.

def test_a_virgin_profile_knows_nothing(isolated_db):
    from services.personality import familiarity

    f = familiarity.get_familiarity()
    assert f["known"] == 0, f"a database nobody has spoken to reports {f['known']} known: {f}"
    assert familiarity.knows_operator() is False


def test_onboarding_with_no_answers_stores_nothing(isolated_db):
    """Driven through the real code path, not asserted from source: the interview is completed
    with an empty response set, exactly as a user who clicks through without answering."""
    from services.personality import familiarity
    from services.user.onboarding_interview import OnboardingInterview

    iv = OnboardingInterview()
    iv.start()
    iv._state.responses = {}
    iv._apply_personality_prefs()

    f = familiarity.get_familiarity()
    assert f["known"] == 0, (
        "running onboarding without answering anything produced "
        f"{[a['key'] for a in f['answers'] if a['known']]}. Those are the program's defaults, "
        "not things the operator told her."
    )
    assert familiarity.knows_operator() is False


def test_an_empty_quiz_does_not_persist_the_neutral_seed(isolated_db):
    """The stats seed at 5 for display. A seed is not an answer, so it must not be stored as one."""
    from services.personality import familiarity
    from services.personality.operator_quiz import save_identity_kv, score_answers

    preview, kv = score_answers([], seed_identity=None)
    assert preview["stats"], "the preview must still carry all six stats for the UI sliders"
    assert not [k for k in kv if k.startswith("stat_")], f"an empty quiz persisted stats: {kv}"

    save_identity_kv(kv)
    assert familiarity.get_familiarity()["known"] == 0


def test_a_real_answer_still_counts(isolated_db):
    """The positive half — without it, every assertion above passes by storing nothing at all."""
    from services.personality import familiarity
    from services.personality.operator_quiz import QUESTIONS, save_identity_kv, score_answers

    q = QUESTIONS[0]
    _preview, kv = score_answers(
        [{"question_id": q.id, "option_id": q.options[0].id}], seed_identity=None
    )
    assert [k for k in kv if k.startswith("stat_")], "a genuine answer stored no stats"
    save_identity_kv(kv)
    f = familiarity.get_familiarity()
    assert f["known"] > 0, "the operator answered a question and familiarity still reads 0"
    assert familiarity.knows_operator() is True


def test_onboarding_stores_what_the_operator_actually_answered(isolated_db):
    """And the other positive half: real answers must survive the change."""
    from services.personality import familiarity
    from services.user.onboarding_interview import OnboardingInterview

    iv = OnboardingInterview()
    iv.start()
    iv._state.responses = {
        "personality": {"formality_level": "formal", "humour_preference": "dry"},
        "communication": {"verbosity": "brief", "proactivity": "high"},
    }
    iv._apply_personality_prefs()

    ticked = {a["key"] for a in familiarity.get_familiarity()["answers"] if a["known"]}
    assert {"formality_level", "humour_preference", "proactivity_level",
            "preferred_response_length"} <= ticked, f"real answers were dropped: {ticked}"
