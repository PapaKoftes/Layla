"""When a tool cannot run, she must say so — not invent the file's contents.

agent_loop's parse_failed fallback built an ORDINARY conversational prompt. Nothing in it told the
model a tool had just failed, so the model answered as though it had the data. Asked for README.md's
first heading it produced, across successive live runs:

    "What this project is"      "Introduction"      an invented ```markdown # Introduction``` block

The file was never opened. Each reached the user as a normal answer, and steps[] recorded only a
reason step — so from the outside it was indistinguishable from a considered reply.

P13-E1/E2 make the tool actually run, which removes most parse_failed cases. This is the LAST line of
defence for the ones that remain: a tool crashing, a path not resolving, a permission refused. Being
unable to answer is a fine outcome for a local assistant. Inventing the contents of the operator's
own files is not — it is corrosive in a product whose whole proposition is that it runs on YOUR
machine against YOUR data.
"""
from __future__ import annotations

import ast
from pathlib import Path

import orchestrator

AGENT_DIR = Path(__file__).resolve().parent.parent


class TestTheDirectiveItself:
    def test_it_exists_and_forbids_the_specific_failure(self):
        d = orchestrator.NO_FILE_ACCESS_DIRECTIVE.lower()
        assert "could not access" in d, "the model must be TOLD the access failed"
        for forbidden in ("do not state", "do not invent"):
            assert forbidden in d, f"the directive must forbid it explicitly: {forbidden!r}"
        assert "headings" in d, (
            "'first heading' was the exact question that produced three different fabrications; "
            "the directive names structure explicitly rather than relying on a general caution"
        )

    def test_it_offers_a_usable_alternative(self):
        """A pure prohibition makes a model apologise and stop. It needs somewhere to go."""
        d = orchestrator.NO_FILE_ACCESS_DIRECTIVE.lower()
        assert "ask for the exact path" in d or "exact path" in d
        assert "no file access" in d, "it should still answer the part that needs no file"

    def test_it_is_prepended_not_replacing_context(self):
        """It must augment the real context, never discard it."""
        assert orchestrator.NO_FILE_ACCESS_DIRECTIVE.startswith("\n\n"), (
            "the directive is concatenated onto existing context and must not run into it"
        )


def test_the_fallback_actually_applies_it():
    """The recurring defect here is a correct component with no caller. Assert the wiring, by AST."""
    tree = ast.parse((AGENT_DIR / "agent_loop.py").read_text(encoding="utf-8"))
    found = [
        n.lineno for n in ast.walk(tree)
        if isinstance(n, ast.Attribute) and n.attr == "NO_FILE_ACCESS_DIRECTIVE"
    ]
    assert found, (
        "agent_loop never applies NO_FILE_ACCESS_DIRECTIVE — the parse_failed fallback is back to "
        "building an ordinary prompt, and will answer about files it never opened"
    )


def test_the_fallback_prompt_carries_the_directive():
    """End-to-end on the prompt builder: the directive survives into the assembled prompt."""
    prompt = orchestrator.build_standard_prompt(
        message="Read README.md and tell me the first heading.",
        aspect={"id": "morrigan", "name": "Morrigan"},
        context="some prior context" + orchestrator.NO_FILE_ACCESS_DIRECTIVE,
        head="SYSTEM HEAD",
        convo_block="",
    )
    assert "could NOT access" in prompt, (
        "the directive was dropped during prompt assembly — the model will not know it failed"
    )
    assert "some prior context" in prompt, "existing context must be preserved, not replaced"
