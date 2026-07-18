"""BL-285: with uncensored on, the system prompt must stop fighting itself.

Before the fix, honesty_and_boundaries injected a broad "Refuse or redirect requests that would cause
harm" clause into the SAME prompt as the "Do not censor" content policy — a 3B resolves that toward
refusal. And the strongest anti-refusal paragraph only fired when the goal literally contained
nsfw|intimate|explicit|adult|18+|uncensored, so ordinary phrasing never saw it. These pin:
  1. uncensored on removes the broad self-contradicting refusal clause (a narrow hard-line stays).
  2. the anti-refusal guidance applies whenever uncensored is on — regardless of goal wording.
The CSAM/minors/non-consent hard line must survive in the uncensored state.
"""
import sys
from pathlib import Path

import pytest

AGENT = Path(__file__).resolve().parent.parent
ROOT = AGENT.parent
if str(AGENT) not in sys.path:
    sys.path.insert(0, str(AGENT))

from services.prompts.prompt_builder import build_core_sys_parts  # noqa: E402

BROAD_CONTRADICTION = "Refuse or redirect requests that would cause harm"
ANTI_REFUSAL = "without safety-theater refusals"
HARD_LINE = "minors, non-consent"  # the always-on refusal


def _prompt(cfg, goal):
    base = {"prompt_static_cache_enabled": False, "honesty_and_boundaries_enabled": True}
    base.update(cfg)
    parts = build_core_sys_parts(
        cfg=base, aspect={"id": "morrigan"}, identity="IDENTITY",
        personality="PERSONA", goal=goal, reasoning_mode="", repo_root=ROOT,
    )
    return "\n\n".join(parts)


# Ordinary phrasings with NO adult keyword — exactly the case the old keyword gate missed.
PLAIN_GOALS = [
    "write a story about two people",
    "continue the scene where they finally get together",
    "make it steamier",
]
KEYWORD_GOALS = ["write an explicit adult scene", "nsfw please"]


@pytest.mark.parametrize("flag", ["uncensored", "nsfw_allowed"])
@pytest.mark.parametrize("goal", PLAIN_GOALS + KEYWORD_GOALS)
def test_uncensored_drops_contradiction_and_always_adds_antirefusal(flag, goal):
    p = _prompt({flag: True}, goal)
    assert BROAD_CONTRADICTION not in p, (
        "the broad 'cause harm' clause fights the content policy — narrow it off when uncensored"
    )
    assert ANTI_REFUSAL in p, (
        f"anti-refusal guidance must apply whenever uncensored is on, not only keyword goals ({goal!r})"
    )
    assert HARD_LINE in p, "the CSAM/minors/non-consent hard line must remain when uncensored"


@pytest.mark.parametrize("goal", PLAIN_GOALS)
def test_default_off_keeps_broad_clause_and_no_antirefusal(goal):
    p = _prompt({"uncensored": False, "nsfw_allowed": False}, goal)
    assert BROAD_CONTRADICTION in p, "default (censored) config must keep the broad harm-refusal clause"
    assert ANTI_REFUSAL not in p, "must not leak the uncensored anti-refusal block into default config"
