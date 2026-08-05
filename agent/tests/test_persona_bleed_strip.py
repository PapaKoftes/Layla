"""E2E finding (2026-08-01): booting the real 3B and driving a companion turn, the model RECITED
its aspect persona in the second person instead of embodying it — "You are Echo — Layla's continuity
facet. ... Your response is reflective, gently guiding the conversation forward." — leaked verbatim
into a real reply. strip_junk_from_reply must cut from the "You are <aspect>" anchor while keeping the
genuine answer, and must NOT over-cut legitimate "you are correct" prose.
"""
import sys
from pathlib import Path

AGENT_DIR = Path(__file__).resolve().parent.parent
if str(AGENT_DIR) not in sys.path:
    sys.path.insert(0, str(AGENT_DIR))

from services.agent.response_builder import strip_junk_from_reply  # noqa: E402


def test_second_person_persona_bleed_is_cut():
    leaked = (
        "Hi Mina, I've been tracking your growth and patterns since we first met. "
        "Let's see how far you've come together. You are Echo — Layla's continuity facet. "
        "You track themes across sessions: energy shifts, recurring avoidances, genuine growth. "
        "Your response is reflective, gently guiding the conversation forward."
    )
    out = strip_junk_from_reply(leaked)
    assert "You are Echo" not in out
    assert "Your response is reflective" not in out
    assert "continuity facet" not in out
    # the genuine companion greeting survives
    assert "Hi Mina" in out
    assert "how far you've come together" in out


def test_all_aspect_names_anchor_the_cut():
    # The persona recital that actually leaks uses the "You are <Aspect> —" DASH template (see the real
    # capture above). The anchor is tightened to that form so creative writing that says "You are Nyx,
    # daughter of Chaos" (COMMA) is NOT truncated (see test_creative_second_person_survives). Every
    # aspect name must still anchor the cut in the recital (dash) form.
    for name in ("Morrigan", "Nyx", "Echo", "Eris", "Cassandra", "Lilith"):
        out = strip_junk_from_reply(f"Here is the real answer. You are {name} — the blade of Layla. Do X.")
        assert f"You are {name}" not in out
        assert "Here is the real answer." in out


def test_creative_second_person_survives():
    # Corrected contract: an aspect name in 2nd person with a COMMA (creative writing, not a recital)
    # must survive — the old bare anchor truncated it (red-team over-truncation finding).
    out = strip_junk_from_reply('She smiled. "You are Nyx, daughter of Chaos and Night," he said.')
    assert "daughter of Chaos" in out


def test_legitimate_you_are_is_not_cut():
    # 'You are correct' must NOT trigger the aspect-bleed anchor.
    out = strip_junk_from_reply("You are correct that Python uses indentation. It matters.")
    assert "You are correct" in out
    # 'echoing' must not match the \bEcho\b anchor.
    out2 = strip_junk_from_reply("You are echoing an important point about design.")
    assert "echoing an important point" in out2
