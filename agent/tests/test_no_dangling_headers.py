"""A truncated section must never end on a heading with nothing under it.

Measured defect (2026-07-19): every ORDINARY turn driven with the real Morrigan persona ended its
persona block on the literal string `## Chat style...` — a heading, an ellipsis, and no body. The
section budget cut at a line boundary that happened to fall just after the heading.

Why this is a defect and not cosmetics: the head is instructions. A heading announces a section that
then does not exist, and a small model imitates the shape of what it is given. It is also a reliable
signal that the budget is being spent on a header nobody can act on.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

AGENT = Path(__file__).resolve().parent.parent
if str(AGENT) not in sys.path:
    sys.path.insert(0, str(AGENT))

from services.context.context_manager import (  # noqa: E402
    _drop_dangling_headers,
    token_estimate,
    truncate_to_tokens,
)


def _trailing_bare_header(text: str) -> str | None:
    """The last heading in `text` that has no non-heading body line after it."""
    lines = [ln for ln in text.split("\n")]
    for i in range(len(lines) - 1, -1, -1):
        s = lines[i].strip()
        if not s:
            continue
        return s if s.startswith("#") else None
    return None


# --------------------------------------------------------------------------------------------
# The primitive
# --------------------------------------------------------------------------------------------

def test_truncation_does_not_end_on_a_bare_heading():
    """The exact shape measured in production, reduced to the primitive that produces it.

    THE SWEEP IS THE TEST. It used to be `range(120, 260, 7)` — 20 budgets that ALL cut inside the
    first body, hundreds of tokens before "## Chat style" (which starts around token 667). No sample
    ever landed near a heading, so the shape it is named for was never constructed: with the fix
    deleted at its call site, this test stayed green and only the three production-path tests below
    went red. A sweep that cannot reach the defect is decoration.

    Swept at step 1 across the whole range instead, so the budgets that land the cut just after a
    heading are actually visited. Verified against the unfixed code: 10 budgets (667-676) produce
    `## Chat style...` with nothing under it.
    """
    body = "\n".join(f"- persona rule number {i} that says something specific" for i in range(60))
    text = "## Core\n" + body + "\n\n## Chat style\n" + body
    total = token_estimate(text)

    # Step 1: the window where a cut can land just after a heading is only ~10 tokens wide, and a
    # coarse step steps straight over it.
    for max_tok in range(20, total):
        out = truncate_to_tokens(text, max_tok)
        assert _trailing_bare_header(out) is None, (
            f"truncate_to_tokens({max_tok}) ended on a bare heading: {out[-80:]!r}"
        )


def test_drop_dangling_headers_removes_header_and_the_blank_lines_before_it():
    assert _drop_dangling_headers("body text\n\n## Chat style") == "body text"
    assert _drop_dangling_headers("body text\n\n## A\n\n### B") == "body text"
    assert _drop_dangling_headers("## Core\nreal body") == "## Core\nreal body"


def test_drop_dangling_headers_returns_empty_when_everything_is_a_header():
    """The caller relies on this to fall back rather than emit an empty section."""
    assert _drop_dangling_headers("## A\n## B") == ""


def test_a_header_with_a_body_is_never_dropped():
    """The fix must not eat content. A heading followed by anything real stays."""
    text = "## Core\n" + "\n".join(f"- rule {i}" for i in range(40))
    out = truncate_to_tokens(text, 60)
    assert out.startswith("## Core"), "the fix removed a heading that HAD a body"
    assert "- rule 0" in out


def test_level_one_headings_are_dropped_too():
    r"""A dangling `# Heading` counts, not just `##`.

    Recorded because narrowing the predicate to `^#{2,6}\s` — to stop trailing `# NOTE:` code
    comments being eaten — was tried and reverted. The head contains genuine LEVEL-1 headings from
    the knowledge and workspace sections, and under the CI stub config an ordinary turn then ended on
    a bare `# API design patterns...`, which is precisely the production defect this module exists to
    catch (`test_ordinary_turn_head_has_no_empty_persona_section` went red).

    The comment-eating limitation is real and documented on `_drop_dangling_headers`; it is the
    smaller harm, and level is not the signal that distinguishes a heading from a comment.
    """
    assert _drop_dangling_headers("body\n\n# API design patterns") == "body"
    assert _drop_dangling_headers("body text\n\n## Chat style") == "body text"
    assert _drop_dangling_headers("body\n\n#### Deep heading") == "body"


def test_truncation_still_truncates():
    """Guard against 'fixing' this by returning the text uncut."""
    text = "\n".join(f"- line {i} with some words in it" for i in range(200))
    out = truncate_to_tokens(text, 50)
    assert len(out) < len(text)
    assert token_estimate(out) <= 80, f"asked for 50 tokens, got {token_estimate(out)}"


# --------------------------------------------------------------------------------------------
# The production path
# --------------------------------------------------------------------------------------------

def _drive_head(goal, monkeypatch, aspect):
    import runtime_safety as rs
    from services.context.context_manager import record_prompt_metrics
    from services.prompts import system_head_builder as SHB

    record_prompt_metrics({}, 2048)
    _orig = rs.load_config()
    monkeypatch.setattr(
        rs, "load_config",
        lambda: {**_orig, "n_ctx": 2048, "system_head_budget_ratio": 0.22},
    )
    return SHB.build_system_head(goal=goal, aspect=aspect, conversation_history=[])


def _real_morrigan():
    import orchestrator

    aspect = orchestrator.select_aspect("hello", force_aspect="morrigan")
    if not (aspect.get("systemPromptAddition") or "").strip():
        pytest.skip("real Morrigan persona has no systemPromptAddition on this checkout")
    return aspect


def _bare_headers_in(head: str) -> list[str]:
    lines = head.split("\n")
    out = []
    for i, ln in enumerate(lines):
        s = ln.strip()
        if not s.startswith("#"):
            continue
        nxt = next((lines[j].strip() for j in range(i + 1, len(lines)) if lines[j].strip()), None)
        if nxt is None or nxt.startswith("#"):
            out.append(s)
    return out


@pytest.mark.parametrize("goal", [
    "fix this bug in my python code",
    "refactor this module for me",
    "write me a haiku about rain",
])
def test_ordinary_turn_head_has_no_empty_persona_section(goal, monkeypatch):
    """RED before the fix: every one of these ended on `## Chat style...` with no body."""
    head = _drive_head(goal, monkeypatch, _real_morrigan())
    bare = _bare_headers_in(head)
    assert not bare, (
        f"the assembled head contains heading(s) with no body: {bare}. A section that announces itself "
        f"and then says nothing is an instruction the model will imitate."
    )
