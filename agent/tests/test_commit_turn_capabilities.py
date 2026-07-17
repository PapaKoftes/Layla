"""BL-267: a completed chat/agent turn is capability PRACTICE.

record_practice() used to have exactly two callers (scheduler/jobs.py, routers/study.py — both the
STUDY subsystem), so every ordinary turn left the capability levels frozen and the Growth panel showed
a constant. commit_turn is the ONE seam every completed turn crosses; these tests exercise the classifier
+ recorder it now calls, WITHOUT the daemon thread so the assertions are deterministic.

Teeth: break _TASKTYPE_TO_DOMAIN / _KEYWORD_TO_DOMAIN (map "coding" -> None) and
test_coding_turn_classifies_and_records fails at `dom == "coding"` — proving the test catches the exact
wiring, not a tautology.
"""
from __future__ import annotations

from layla.memory.db import get_capability
from services.agent.turn_commit import _practice_domain_for_turn, _record_practice_domain


def test_coding_turn_classifies_and_records():
    """A successful, substantive coding turn classifies to 'coding' and moves the capability row."""
    dom = _practice_domain_for_turn(
        "refactor the auth module and fix the failing pytest", "finished", False, None,
    )
    assert dom == "coding"

    before = (get_capability("coding") or {}).get("practice_count") or 0
    before_level = (get_capability("coding") or {}).get("level") or 0.5
    _record_practice_domain(dom)
    after = get_capability("coding")
    assert after is not None
    assert (after.get("practice_count") or 0) == before + 1
    assert (after.get("level") or 0) > before_level  # level rose from the practice delta


def test_route_decision_reasoning_maps_to_problem_solving():
    """When the run state carries the already-computed route decision, it is reused (no re-classify)."""
    dom = _practice_domain_for_turn(
        "analyze why this approach is slow and compare it to the alternative", "finished", False,
        {"route_decision": {"task_type": "reasoning"}},
    )
    assert dom == "problem_solving"


def test_research_task_type_maps_to_research():
    dom = _practice_domain_for_turn(
        "research the tradeoffs between these two storage engines", "finished", False,
        {"route_decision": {"task_type": "research"}},
    )
    assert dom == "research"


def test_keyword_widens_only_when_task_type_gives_nothing():
    """A chat/default task_type still records the strong low-FP keyword domains."""
    dom = _practice_domain_for_turn(
        "please document the release process for the team", "finished", False,
        {"route_decision": {"task_type": "chat"}},
    )
    assert dom == "writing"


def test_phatic_and_short_turns_record_nothing():
    """"hi" / "thanks" / "why?" are below the word-count floor OR classify to chat -> None."""
    for goal, status in (("hi", "fast_path"), ("thanks!", "fast_path"), ("why?", "finished"),
                         ("explain", "finished"), ("ok cool", "finished")):
        assert _practice_domain_for_turn(goal, status, False, None) is None


def test_failure_statuses_record_nothing():
    """Stricter than _should_learn: a non-successful turn learns the operator's fact but is NOT
    successful practice, so timeout/error/blocked/system_busy/abort record nothing."""
    for status in ("timeout", "error", "blocked", "system_busy", "client_abort",
                   "pipeline_needs_input", "stream_pending"):
        assert _practice_domain_for_turn("refactor the whole module carefully", status, False, None) is None


def test_refused_turn_records_nothing():
    assert _practice_domain_for_turn("refactor the whole module carefully", "finished", True, None) is None


def test_commit_turn_SEAM_actually_records_practice(monkeypatch, tmp_path):
    """The MEDIUM the adversarial verifier flagged: the tests above exercise the HELPERS, but nothing asserted
    that commit_turn (the seam every turn crosses) actually INVOKES the practice path. If someone deleted the
    step-4 wiring in commit_turn, every helper test stays green while capability scores freeze again — the exact
    'guard the artifact, not the wiring' disease this whole phase exists to kill.

    So this drives commit_turn itself and asserts the seam calls record-practice for a real coding turn and
    NOT for a phatic one. It spies on _record_practice_domain (the seam's target) rather than the DB, so it is
    fast and deterministic, and joins the daemon thread commit_turn spawns."""
    import threading
    import runtime_safety
    import services.agent.turn_commit as tc

    # keep the learning LLM out of it — we are testing the practice seam, not extraction
    base = dict(runtime_safety.load_config() or {})
    base.update({"operator_memory_llm_enabled": False, "identity_capture_enabled": False,
                 "auto_title_synthesis_enabled": False})
    monkeypatch.setattr(runtime_safety, "load_config", lambda *a, **k: base)
    monkeypatch.setenv("LAYLA_DATA_DIR", str(tmp_path))  # never the operator DB

    recorded: list[str] = []
    monkeypatch.setattr(tc, "_record_practice_domain", lambda dom: recorded.append(dom))

    def _run(goal, status):
        recorded.clear()
        tc.commit_turn("conv-seam", goal, "some reply text here", aspect_id="morrigan", status=status)
        for t in threading.enumerate():           # let the cap-practice daemon finish
            if t.name == "cap-practice":
                t.join(timeout=5)

    _run("write a python function that reverses a linked list", "finished")
    assert recorded == ["coding"], f"the seam did not record coding practice: {recorded!r}"

    _run("hi", "fast_path")
    assert recorded == [], f"a phatic turn wrongly recorded practice: {recorded!r}"
