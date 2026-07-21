"""Phase 13 criterion 2: an adverb must not cost Layla her only source of capability ground truth.

`_CAP_Q_RE` decides whether the capability manifest — the ~700-token block of VERIFIED facts about
what she can actually do — is injected. It required "you" and "do" to be ADJACENT, so measured on
the live prompt the manifest arrived for "list your capabilities" and "what tools do you have" but
NOT for:

    what can you actually do        what exactly can you do
    what can you really do          what else can you do

Four ordinary phrasings of the same question. The most natural of them is among the failures, and an
intensifier is precisely what a person adds when they suspect the previous answer was padded — so
she fell back to inventing capabilities on exactly the turn where the user was pushing for accuracy.

The negative lookahead that separates the QUESTION from a work REQUEST ("what can you do ABOUT the
memory leak", which must not pay ~700 tokens on an ordinary debugging turn) is untouched, and is
pinned here in both its plain and adverb-bearing forms.
"""
from __future__ import annotations

import pytest

from services.prompts.prompt_builder import _is_capability_question


def _q(text: str) -> bool:
    return _is_capability_question(text.lower())


class TestAdverbsDoNotSuppressTheManifest:
    @pytest.mark.parametrize("goal", [
        "what can you do",
        "what can you actually do",
        "what can you really do",
        "what can you genuinely do",
        "what exactly can you do",
        "what else can you do",
        "what can you even do",
        "tell me what you can actually do",
        "what can you do for me",
        "list your capabilities",
        "what tools do you have",
    ])
    def test_capability_questions_are_recognised(self, goal):
        assert _q(goal), (
            f"{goal!r} did not trigger the capability manifest — she answers this from invention "
            "instead of from verified ground truth"
        )


class TestWorkRequestsStillDoNotPayForIt:
    """The manifest costs ~700 tokens. A work request that opens with the same words must not bill it."""

    @pytest.mark.parametrize("goal", [
        "what can you do about the memory leak",
        "what can you do with this file",
        "what can you do to fix the test",
        "what can you do regarding the failing build",
        # The adverb widening must not punch a hole in the lookahead:
        "what can you actually do about this bug",
        "what exactly can you do with these logs",
        "can you refactor this module",
        "what did the previous run do",
    ])
    def test_work_requests_are_not_capability_questions(self, goal):
        assert not _q(goal), (
            f"{goal!r} was billed ~700 tokens of capability manifest on what is an ordinary work "
            "turn — this is the regression the negative lookahead exists to prevent"
        )


def test_the_widening_is_bounded_to_a_single_adverb():
    """The adverb slot must accept ONE adverb, not degrade into "anything between you and do".

    Written first as `assert not _q("what can you do the thing i asked about earlier do")`, which
    failed — and checking the ORIGINAL pattern showed it matched that too. Pre-existing looseness,
    not a regression from this widening, and "fixing" it here would have been an unrelated behaviour
    change smuggled in under the label of bounding my own edit. Recorded rather than silently
    dropped: the first `what can you do` in a longer sentence matches whenever the following word is
    not one of the lookahead's prepositions. That is worth revisiting on its own merits, and this is
    not that change.
    """
    assert _q("what can you actually do"), "one adverb: the case this widening exists for"
    assert not _q("what can you totally completely do"), "two adverbs must not match"
    assert not _q("what can you supposedly quickly do"), "the slot is one token, not a wildcard"
    assert not _q("what can you tell the user about the do loop"), "'do' as a noun must not match"
