"""CP-4: pin today's answer-extraction behaviour BEFORE CP-5 gives the answer a single owner.

There is no `state["answer"]` anywhere in this codebase. The final user-visible text is INFERRED from
the tail of an append-only step log, by two rules that disagree:

  Rule A (router)    routers/agent.py:1325 and :1477
                     final = steps[-1].get("result", "") if steps else ""
                     -> the LAST step's result, whatever action it was.

  Rule B (finalizer) services/agent/run_finalizer.py:101-104
                     for s in reversed(steps): if s["action"] == "reason": final = s["result"]
                     -> the last REASON step's result; tool steps are skipped.

They return the SAME string when the last step is a reason step, and DIFFERENT strings when the last
step is a tool step — i.e. exactly the multi-step engineering turn, the flagship use case. The router
shows the user the raw tool result; the finalizer evaluates and learns from the last reasoned text.

The suite has HTTP-level coverage of the router but asserts NOTHING about the answer text, because no
expression denotes it — so "the suite stayed green" is worthless evidence precisely where CP-5
operates. This file creates that evidence. It pins the divergence as FACT, it does not fix it. CP-5
removes the divergence and updates this file once; that diff is the human-readable record of the
behaviour change.

── CP-5 UPDATE (2026-07-27): the router answer now HAS an owner ──────────────────────────────────────
`services/agent/turn.py::answer_of(result)` is the single owner of the USER-VISIBLE answer, and both
router readers (streamed + non-streamed) now call it instead of re-deriving the text inline. Crucially
the REAL router was never the bare `rule_a_router` copy below: it prefers the synthesized prose
(`result["response"]`) and only falls back to the last step's result when that is a STRING — so it never
surfaces a raw tool-result dict (the `rule_a_router` copy models only the fallback, which is why its
tool-last case returns a dict). `answer_of` captures the real behaviour and is tested directly below.

What did NOT change: the finalizer's `rule_b_finalizer` (the last *reasoned* text) is a DIFFERENT value
— the input to the off-by-default answer-quality assessment, not the delivered answer. It is
intentionally left as-is; the two were never two rules for one value, they are two different
measurements (delivered answer vs. reasoned text). So this file keeps the Rule B tests as a true record
and adds the owner tests; it does not force the assessment to read the delivered answer.
"""
from __future__ import annotations

import ast
from pathlib import Path

AGENT_DIR = Path(__file__).resolve().parent.parent


# ── The two rules, replicated verbatim from source (see the source-anchor test below, which fails if
#    the originals drift from these copies) ──────────────────────────────────────────────────────

def rule_a_router(steps: list[dict]) -> str:
    """routers/agent.py:1325 / :1477 — the last step's result."""
    return steps[-1].get("result", "") if steps else ""


def rule_b_finalizer(steps: list[dict]) -> str:
    """run_finalizer.py:101-104 — the last reason step's result."""
    final_text = ""
    for s in reversed(steps):
        if s.get("action") == "reason":
            r = s.get("result", "")
            final_text = r if isinstance(r, str) else ""
            break
    return final_text


# ── Turn shapes ──────────────────────────────────────────────────────────────────────────────────

REASON_LAST = [
    {"action": "read_file", "result": {"ok": True, "content": "raw tool payload"}},
    {"action": "reason", "result": "Here is the answer, reasoned from what I read."},
]

TOOL_LAST = [
    {"action": "reason", "result": "Let me read the file to answer that."},
    {"action": "read_file", "result": {"ok": True, "content": "raw tool payload"}},
]


class TestRulesAgreeOnAReasonLastTurn:
    """When the turn ends on a reason step, both rules return that reason text. No divergence."""

    def test_both_rules_return_the_reason_text(self):
        a = rule_a_router(REASON_LAST)
        b = rule_b_finalizer(REASON_LAST)
        assert a == "Here is the answer, reasoned from what I read."
        assert b == "Here is the answer, reasoned from what I read."
        assert a == b, "on a reason-last turn the two paths must agree — this is the common case"


class TestRulesDivergeOnAToolLastTurn:
    """THE recorded divergence. On a tool-last turn — the multi-step engineering turn — the router
    shows the raw tool result while the finalizer learns from the last reasoned text. CP-5 collapses
    this; today it is a fact, pinned so the collapse is a reviewable, deliberate change."""

    def test_router_returns_the_raw_tool_result(self):
        a = rule_a_router(TOOL_LAST)
        assert a == {"ok": True, "content": "raw tool payload"}, (
            "Rule A returns the LAST step's result verbatim — a dict, not prose. This is what a /v1 "
            "client and the streamed done-frame surface to the user on a tool-last turn."
        )

    def test_finalizer_returns_the_last_reasoned_text(self):
        b = rule_b_finalizer(TOOL_LAST)
        assert b == "Let me read the file to answer that.", (
            "Rule B skips the tool step and returns the last reason — a DIFFERENT string from Rule A. "
            "This is what the turn is evaluated and learned from."
        )

    def test_the_two_paths_disagree_here(self):
        assert rule_a_router(TOOL_LAST) != rule_b_finalizer(TOOL_LAST), (
            "the divergence is real and this is the whole reason CP-5 exists; if this ever passes as "
            "equal, the rules have already been unified and CP-5 is done"
        )


class TestEdgeCases:
    def test_empty_steps_both_return_empty_string(self):
        assert rule_a_router([]) == ""
        assert rule_b_finalizer([]) == ""

    def test_no_reason_step_finalizer_returns_empty(self):
        tools_only = [{"action": "read_file", "result": {"ok": True}}]
        assert rule_b_finalizer(tools_only) == "", "no reason step -> Rule B has nothing to return"
        assert rule_a_router(tools_only) == {"ok": True}, "Rule A still returns the last result"


class TestAnswerOfOwnsTheRouterAnswer:
    """CP-5: the real router answer has ONE owner now — services.agent.turn.answer_of. Unlike the
    simplified rule_a_router copy, it prefers the synthesized prose and never returns a raw dict."""

    def test_prefers_the_synthesized_prose_answer(self):
        from services.agent.turn import answer_of
        result = {"response": "The polished answer.", "steps": TOOL_LAST}
        assert answer_of(result) == "The polished answer.", "prose answer wins over the last step"

    def test_reason_last_falls_back_to_the_reason_string(self):
        from services.agent.turn import answer_of
        # no prose response -> fall back to the last step, which here is a reason STRING
        assert answer_of({"steps": REASON_LAST}) == "Here is the answer, reasoned from what I read."

    def test_tool_last_never_returns_a_raw_dict(self):
        from services.agent.turn import answer_of
        # the fallback is a dict (raw tool result) -> answer_of returns "" rather than leak it, the
        # exact safety the real router's `isinstance(final, str)` guard provides (the rule_a copy lacks).
        assert answer_of({"steps": TOOL_LAST}) == "", "a raw tool-result dict must never become the answer"

    def test_empty_run_returns_empty_string(self):
        from services.agent.turn import answer_of
        assert answer_of({}) == "" and answer_of({"steps": []}) == ""


def test_the_source_rules_still_match_these_copies():
    """Guards the whole file against drift: if Rule B changes in source but not here, this
    characterization is a lie. Rule A was replaced by CP-5's answer_of() owner — so we now anchor on the
    owner call in the router AND on the surviving fallback literal (kept for the non-stream retry)."""
    router = (AGENT_DIR / "routers" / "agent.py").read_text(encoding="utf-8")
    finalizer = (AGENT_DIR / "services" / "agent" / "run_finalizer.py").read_text(encoding="utf-8")

    # CP-5: both router readers now route through the one owner.
    assert "answer_of(result)" in router, (
        "the router no longer calls answer_of() — CP-5's single-owner unification was reverted or moved; "
        "update this file to match the new answer source"
    )
    # The fallback literal still lives inside the non-stream reader's post-clean retry.
    assert 'steps[-1].get("result", "") if steps else ""' in router, (
        "the last-step fallback literal changed — update this file"
    )
    # Rule B (finalizer) is a DIFFERENT, unchanged value; anchor on both its lines.
    assert 'for s in reversed(state.get("steps", []))' in finalizer, "Rule B's reverse-scan changed"
    assert 's.get("action") == "reason"' in finalizer, "Rule B's reason-match changed"
