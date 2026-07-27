"""CP-3 severance regression: `outcome_evaluated` must fire on the NON-STREAMED turn too.

`outcome_evaluated` is the learning-feedback liveness signal. A real-model eval run
(scripts/run_real_eval.py) drives EVERY case with ``stream: false`` (eval/run_golden.py posts
stream=False to both /v1 and /agent), and its liveness snapshot showed outcome_evaluated=0 across
the committed turns — while outcome_evaluations rows were still being written. That 0 was a severed
SIGNAL, not a severed pipeline:

  * run_finalizer.finalize_run_state evaluates the run on the NON-streamed path (it is reached with
    status=="finished"), sets ``state["outcome_evaluation"]`` and persists the DB row via
    session_context.set_outcome_evaluation -> save_outcome_evaluation ... but it NEVER fires liveness.
  * commit_turn USED to fire liveness only INSIDE its own compute-if-absent block
    (``if state is not None and not (state.get("outcome_evaluation") or {})``). On the non-streamed
    path that block is skipped, because the field run_finalizer already set is present. So the only
    fire() site never ran for any non-streamed turn.

The very field the run_finalizer caller sets to do its job suppressed the fire the signal depends on
(a caller sets one field; the fire checked that same field's absence). The fix fires at the TURN
BOUNDARY keyed on the turn CARRYING an evaluation, covering both the streamed path (commit_turn
computes the evaluation) and the non-streamed path (run_finalizer computed it), exactly once per turn
because commit_turn runs exactly once per turn.
"""
from __future__ import annotations

import pytest


class _DummyThread:
    """Neutralise commit_turn's daemon side-effects (title synth, skill-acquire, auto-learn,
    capability practice) so the test is deterministic and leaks no background DB writes past the
    function-scoped isolated_db teardown. The outcome evaluation + persist + fire are all SYNCHRONOUS
    inside commit_turn, so this does not touch what is under test."""

    def __init__(self, *a, **k):
        pass

    def start(self):
        pass


@pytest.fixture
def quiet_commit(monkeypatch):
    from services.agent import turn_commit

    monkeypatch.setattr(turn_commit.threading, "Thread", _DummyThread)
    monkeypatch.setattr(
        "services.memory.conversation_entity_extractor.extract_in_background",
        lambda *a, **k: None,
    )
    return turn_commit


def _outcome_row_count(cid: str) -> int:
    """Count persisted outcome_evaluations rows for a conversation via direct SQL.

    Deliberately NOT via layla.memory.db.get_last_outcome_evaluation_record: that reader calls
    ``.get()`` on a ``sqlite3.Row`` (which has no ``.get``) and raises — a separate latent bug we
    do not want this test to depend on. We only need to prove the durable row exists.
    """
    from layla.memory.db_connection import _conn

    with _conn() as db:
        return int(
            db.execute(
                "SELECT COUNT(*) AS n FROM outcome_evaluations WHERE conversation_id = ?", (cid,)
            ).fetchone()["n"]
        )


def _substantive_state(cid: str, **over) -> dict:
    """A finished, tool-using turn — the kind that legitimately warrants an outcome evaluation."""
    st = {
        "status": "finished",
        "conversation_id": cid,
        "original_goal": "read the config file and summarise the tool budgets",
        "steps": [{"action": "read_file", "args": {"path": "runtime_config.json"}, "result": {"ok": True}}],
    }
    st.update(over)
    return st


def test_non_streamed_finished_turn_fires_outcome_evaluated(isolated_db, quiet_commit):
    """THE regression. Reproduces the eval-harness non-streamed path: run_finalizer has already
    evaluated the run and persisted the row; commit_turn then runs at the turn boundary. The signal
    MUST fire here — before the fix it did not, which is exactly the eval-run 0."""
    from services.infrastructure.session_context import get_or_create_session
    from services.observability import liveness

    cid = "eval-nonstreamed-1"
    ev = {"success": True, "score": 0.86, "issues": []}
    # Exactly what run_finalizer.finalize_run_state does on the non-streamed path (its lines 44-48):
    # set the field on state AND persist the outcome_evaluations row — WITHOUT firing liveness.
    state = _substantive_state(cid, outcome_evaluation=ev)
    get_or_create_session(cid).set_outcome_evaluation(ev)

    before = liveness.snapshot()["outcome_evaluated"]["count"]

    quiet_commit.commit_turn(
        cid,
        "read the config file and summarise the tool budgets",
        "The config caps tool calls at 3 and runtime at 60s.",
        aspect_id="morrigan",
        status="finished",
        state=state,
    )

    after = liveness.snapshot()["outcome_evaluated"]["count"]
    assert after == before + 1, (
        "a NON-streamed finished substantive turn did not fire outcome_evaluated. This is the "
        "eval-run 0: run_finalizer set state['outcome_evaluation'] (and wrote the row), and that "
        "presence made commit_turn skip its only fire() site."
    )

    # The durable learning row is present on the non-streamed path (written by run_finalizer's
    # set_outcome_evaluation, modelled above) — the learning pipeline itself was never severed.
    assert _outcome_row_count(cid) >= 1, "no outcome_evaluations row was written for the turn"


def test_streamed_finished_turn_computes_row_and_fires(isolated_db, quiet_commit):
    """Regression guard for the path commit_turn owns end-to-end. A streamed turn hands commit_turn
    the stream_pending placeholder and NO evaluation; commit_turn computes it, persists the row, and
    fires. This proves commit_turn's own pipeline is live (not just the setup in the test above)."""
    from services.observability import liveness

    cid = "eval-streamed-1"
    state = _substantive_state(cid, status="stream_pending")  # resolved to finished inside commit_turn

    before = liveness.snapshot()["outcome_evaluated"]["count"]

    quiet_commit.commit_turn(
        cid,
        "read the config file and summarise the tool budgets",
        "The config caps tool calls at 3 and runtime at 60s.",
        aspect_id="morrigan",
        status="finished",
        state=state,
    )

    assert state.get("outcome_evaluation"), "streamed turn produced no outcome evaluation"
    assert _outcome_row_count(cid) >= 1, "commit_turn did not persist the outcome_evaluations row"
    after = liveness.snapshot()["outcome_evaluated"]["count"]
    assert after == before + 1, "streamed turn did not fire outcome_evaluated"
