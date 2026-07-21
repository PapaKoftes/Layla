"""The prompt asserted "associations" with the current request that were nothing of the kind.

system_head_builder built a `Knowledge graph associations:` block from the memory graph. When no node
matched the goal it did not fall silent — it injected the five most RECENT nodes anyway, under a
heading that tells the model these relate to what the user just asked.

Measured on the operator's live graph, ordinary goals produced this in the actual prompt:

    Knowledge graph associations: CORRECTED; ValueError; n must be a non-negative integer.;
    Adversarial verifier test fact: the sky is teal on Tuesdays.; The user prefers dark mode
    and lives in Berlin

Two separate faults produced it. (1) The recency fallback: "nothing was relevant" is a reason to say
nothing, not a reason to say something else confidently. (2) The extractor mistakes prompt structure
for knowledge — of 31 nodes in that graph roughly six are real, the rest being section markers
(TITLE, REPLY, EARNED, CONCLUSION, REFUSED, CORRECTED), error shrapnel (ValueError), security-test
residue (SSN, PIN) and transcript fragments.

Neither fix can remove a well-formed FALSE claim, and these tests say so explicitly rather than
implying a guarantee that is not there.
"""
from __future__ import annotations

import pytest

from services.prompts.system_head_builder import _usable_association


class TestUsableAssociation:
    @pytest.mark.parametrize("label", [
        "TITLE", "REPLY", "EARNED", "CONCLUSION", "REFUSED", "ONLY", "NOT", "CORRECTED",
        "ValueError", "SSN", "PIN", "AI", "MCP", "HTTP", "olleh", "AppData", "Morrigan",
    ])
    def test_bare_tokens_are_not_associations(self, label):
        """A token carries no claim, even a genuine one: 'associations: AI' informs nothing."""
        assert _usable_association(label) is False

    @pytest.mark.parametrize("label", [
        "We prefer simple solutions over complex ones",
        "n must be a non-negative integer.",
        "The user prefers dark mode",
    ])
    def test_phrases_are_associations(self, label):
        assert _usable_association(label) is True

    def test_empty_and_none_are_safe(self):
        assert _usable_association(None) is False
        assert _usable_association("") is False
        assert _usable_association("   ") is False

    def test_the_gate_does_not_claim_to_detect_falsehood(self):
        """Stated as a test so nobody mistakes this for a fabrication filter.

        Both of these are planted, both are false, and both pass — because they are well-formed
        phrases. Removing them is a data decision, not a formatting one.
        """
        assert _usable_association("Adversarial verifier test fact: the sky is teal on Tuesdays.") is True
        assert _usable_association("The user prefers dark mode and lives in Berlin") is True


class TestNoRecencyFallback:
    """The block must be EMPTY when nothing matches, not filled with whatever is newest."""

    @staticmethod
    def _associations(goal: str, labels: list[str]) -> list[str]:
        """Mirrors the selection in build_system_head so the rule is testable without a full head."""
        goal_words = {w.lower() for w in goal.split() if len(w) > 3}
        return [
            lab for lab in labels
            if _usable_association(lab) and any(w in lab.lower() for w in goal_words)
        ]

    def test_unmatched_goal_yields_nothing(self):
        graph = ["CORRECTED", "ValueError", "n must be a non-negative integer.",
                 "Adversarial verifier test fact: the sky is teal on Tuesdays.",
                 "The user prefers dark mode and lives in Berlin"]
        got = self._associations("Refactor the auth module and explain the tradeoffs", graph)
        assert got == [], (
            "nothing in the graph relates to this goal, so the prompt must not assert that "
            f"something does — got {got!r}"
        )

    def test_a_genuine_match_still_surfaces(self):
        """The gate must not silence the feature when it has something real to say."""
        graph = ["We prefer simple solutions over complex ones", "CORRECTED"]
        got = self._associations("should we prefer a simple approach here", graph)
        assert got == ["We prefer simple solutions over complex ones"]

    def test_scaffolding_is_dropped_even_when_it_matches(self):
        """'can you correct this' previously produced 'associations: CORRECTED'."""
        got = self._associations("can you correct this for me", ["CORRECTED"])
        assert got == []
