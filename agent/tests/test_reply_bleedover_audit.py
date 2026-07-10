"""Regression guards for the GSD reply-bleedover audit (the "two tags, one broken" cluster,
the `##`-heading answer-wipe, deliberation POV leak, stop-sequence dead-config, title-tag leak,
and the length-rule wording). Each test pins a specific adversarially-verified finding so the
defect cannot silently return.
"""
import sys
from pathlib import Path

AGENT_DIR = Path(__file__).resolve().parent.parent
if str(AGENT_DIR) not in sys.path:
    sys.path.insert(0, str(AGENT_DIR))

from services.agent.response_builder import (  # noqa: E402
    clean_response_text,
    stream_safe_prefix,
    strip_junk_from_reply,
)

_SIG = "⚔"  # ⚔ Morrigan's sigil


# ── 1. Leading speaker/persona label — every leaked form strips (the "two tags") ───────────────

def test_leading_label_forms_are_stripped():
    cases = [
        ("Morrigan: Here is the fix.", "Here is the fix."),
        ("morrigan: four", "four"),                                   # lowercase
        ("Layla: four", "four"),                                      # base identity name
        (_SIG + " Morrigan: The answer is 42.", "The answer is 42."),  # sigil + name + colon
        (_SIG + " Morrigan\nHere is the fix.", "Here is the fix."),    # sigil + name + newline
        ("**Morrigan:** use a set.", "use a set."),                   # markdown bold
        ("*Morrigan* Here is the fix.", "Here is the fix."),          # markdown italic
        ("> Morrigan: cap the retry loop.", "cap the retry loop."),   # blockquote
        ("Layla " + _SIG + " Morrigan: Here it is.", "Here it is."),  # full composite chip form
        ("## Morrigan\nHere is the fix.", "Here is the fix."),        # heading + name (DE-LABEL)
    ]
    for raw, expected in cases:
        assert strip_junk_from_reply(raw) == expected, raw


def test_legit_prose_and_headings_are_never_stripped():
    # Name-gated: these must pass through untouched (an aspect name in prose, or a real heading).
    keep = [
        "Layla is an AI assistant that helps with code.",
        "Morrigan is the war goddess in Celtic myth.",
        "Nyx and Echo are two of the aspects available.",
        "Echo the input back to the user.",
        "cassandra predicted it would rain.",
        "The answer is 42 ## Context matters here.",   # mid-line ## must survive
    ]
    for raw in keep:
        assert strip_junk_from_reply(raw) == raw, raw


# ── 2. The `##`-heading answer-wipe (the worst finding) — legit headings must SURVIVE ──────────

def test_leading_markdown_heading_answer_is_not_wiped_to_empty():
    # A reply that legitimately opens with a markdown heading used to be truncated to "" at the
    # bare `##` marker → replaced by the "Sorry — I couldn't generate a response" fallback.
    for raw in (
        "## Overview\nREST is an architectural style for APIs.",
        "## Deploy checklist\n1. Run tests\n2. Push",
        "### Summary\nThe function returns a list.",
    ):
        out = strip_junk_from_reply(raw)
        assert out.strip(), f"legit heading answer wiped to empty: {raw!r}"
        assert "REST" in out or "Run tests" in out or "returns a list" in out


def test_leaked_scaffold_headers_are_still_truncated():
    # Removing the bare `##` cut must NOT let scaffold-section echoes leak.
    assert strip_junk_from_reply("Here is the answer.\n\n## SYSTEM\nYou are Layla...") == "Here is the answer."
    assert strip_junk_from_reply("ok done.\n## TASK\nrepeat the prompt") == "ok done."


# ── 3. Streaming: a complete leading label never flashes live ──────────────────────────────────

def test_stream_safe_prefix_does_not_flash_leading_label():
    delta, _ = stream_safe_prefix("Morrigan: hey there", 0)
    assert not delta.lstrip().startswith("Morrigan"), delta
    delta2, _ = stream_safe_prefix(_SIG + " Morrigan: hi", 0)
    assert _SIG not in delta2 and "Morrigan" not in delta2, delta2


def test_stream_safe_prefix_passes_ordinary_text():
    delta, emitted = stream_safe_prefix("Here is the answer.", 0)
    assert delta == "Here is the answer."


def _stream_live(tokens):
    """Reconstruct what the client actually paints, feeding tokens ONE AT A TIME the way the
    router does (buffer grows, stream_safe_prefix called per token). The re-audit found the
    single-buffer test missed this incremental path — the label completes before the answer."""
    buf, emitted, live = "", 0, ""
    for tk in tokens:
        buf += tk
        delta, emitted = stream_safe_prefix(buf, emitted)
        live += delta
    return live


def test_stream_incremental_never_flashes_label_and_reconstructs_answer():
    # Each case: tokens streamed one at a time -> the live-painted text must equal the clean answer
    # with NO leaked label and NO mangling (the "Morriganan:" counter-desync bug).
    # label cases: the leaked tag must NEVER appear in the live-painted text
    label_cases = [
        (["##", " Mor", "rig", "an", "\n", "The", " capital", " is", " Paris."], "The capital is Paris."),
        (["Mor", "rig", "an", ":", " The", " answer", " is", " 4."], "The answer is 4."),
        ([_SIG, " Mor", "rig", "an", ":", " Hello", " there"], "Hello there"),
        (["Layla", ":", "\n", "Paris."], "Paris."),
        (["**", "Nyx", ":", "**", " Layered", " take."], "Layered take."),
        # composite chip form "Layla ⚔ Morrigan:" split across tokens (the round-5 leak+mangle case)
        (["Layla", " " + _SIG, " Mor", "rigan", ":", " The", " capital", " is", " Paris", "."], "The capital is Paris."),
        (["Layla", " Morrigan", ":", " answer", " here"], "answer here"),
    ]
    for tokens, expected in label_cases:
        live = _stream_live(tokens)
        assert live.strip() == expected, f"{tokens!r} -> {live!r} (expected {expected!r})"
        for bad in ("Morrigan", "Layla", "Nyx", _SIG):
            assert bad not in live, f"leaked {bad!r} in live stream {live!r}"
    # non-label cases: reconstruct exactly (name-in-prose and plain prose both stream whole)
    for tokens, expected in [
        (["Morrigan", " is", " a", " goddess."], "Morrigan is a goddess."),
        (["The", " answer", " is", " 42."], "The answer is 42."),
    ]:
        assert _stream_live(tokens).strip() == expected


def test_echo_memory_marker_truncates_not_strips_in_place():
    # A leading "[ECHO: …]" is a truncation point, not an inline tag; it must null the whole leak
    # fragment ("[ECHO: note] leaked" -> "") rather than strand "leaked". Regression: the per-aspect
    # strip (…ECHO…) removed just the bracket and left the fragment.
    assert strip_junk_from_reply("[ECHO: internal note] leaked") == ""
    assert strip_junk_from_reply("[Echo (patterns/preferences): x]") == ""
    # legit mid-line shell 'echo:' is untouched
    assert strip_junk_from_reply("To print: echo: hello world") == "To print: echo: hello world"


def test_dash_separated_leading_label_stripped_but_hyphens_safe():
    assert strip_junk_from_reply("Morrigan - here is the fix.") == "here is the fix."
    assert strip_junk_from_reply(_SIG + " Nyx — cap retries.") == "cap retries."
    # hyphenated words and em-dash asides in prose must survive
    assert strip_junk_from_reply("Morrigan-based routing is used here.") == "Morrigan-based routing is used here."
    assert strip_junk_from_reply("The build - which is slow - needs a cache.") == "The build - which is slow - needs a cache."


def test_completion_gate_default_is_off():
    # completion_gate_enabled=True appends retry-injection text a weak model can echo verbatim into
    # the reply. The runtime loader default had drifted to True (schema says False); realigned.
    import runtime_safety
    assert runtime_safety.load_config().get("completion_gate_enabled") is False


# ── Round 3: [TOOL:] body, reasoning traces, bracket-colon, custom names, delib POV, debate ──────

def test_tool_marker_truncates_its_body():
    # [TOOL: …] is a truncation point; the ALLCAPS-colon strip used to remove just the bracket and
    # leave the tool body in the reply.
    assert strip_junk_from_reply("Here is the summary.\n[TOOL: web_search]\nquery: paris\nRAW: leaked") == "Here is the summary."
    assert strip_junk_from_reply("The answer.\n---\n[TOOL: markdown]\n# Report\nbody") == "The answer."


def test_reasoning_traces_stripped():
    assert strip_junk_from_reply("<think>reasoning</think>\nThe capital of France is Paris.") == "The capital of France is Paris."
    assert strip_junk_from_reply("<thinking>\nplan\n</thinking>\n\nHere is the code.") == "Here is the code."
    assert strip_junk_from_reply("<scratchpad>work</scratchpad>Answer here.") == "Answer here."
    assert strip_junk_from_reply("<think>cut off mid thought at max tokens") == ""   # dangling
    # legit angle-bracket prose/code must survive
    assert strip_junk_from_reply("Use a < b and c > d to compare.") == "Use a < b and c > d to compare."


def test_reasoning_traces_stripped_in_title():
    from services.agent.title_synthesizer import _clean_title
    assert _clean_title("<think>naming this</think> Math Help") == "Math Help"
    assert _clean_title("<think>") == ""   # dangling opener (stop=['\\n'] cut after <think>)


def test_bracketed_name_with_dangling_colon():
    assert strip_junk_from_reply("[Morrigan]: Here is the answer.") == "Here is the answer."
    assert strip_junk_from_reply("[Nyx]: something") == "something"


def test_custom_aspect_name_stripped_when_threaded():
    assert strip_junk_from_reply("Seraphina: the answer is four.", ("Seraphina",)) == "the answer is four."
    # built-in names still covered with the default (no extra names)
    assert strip_junk_from_reply("Morrigan: hi there") == "hi there"


def test_deliberation_no_marker_pov_dump_does_not_leak():
    import orchestrator
    pov = (
        "[" + _SIG + " MORRIGAN] (blunt): Use a timeout.\n"
        "[✦ NYX] (layered): Cap retries.\n[◎ ECHO] (reflective): seen before."
    )
    reply, _meta = orchestrator.split_deliberation_output(pov, "Morrigan")
    assert not reply.strip(), f"POV dump leaked as reply: {reply!r}"
    # a plain marker-less answer (0–1 labels) is still returned as-is
    reply2, _ = orchestrator.split_deliberation_output("just a plain answer, no markers", "Morrigan")
    assert reply2 == "just a plain answer, no markers"


def test_debate_engine_extract_text_applies_cleaning_floor():
    from services.planning.debate_engine import _extract_text
    assert _extract_text("Layla: Refactor incrementally.\nUser: what about the tests?") == "Refactor incrementally."


def test_extract_artifacts_infostring_and_truncated():
    from routers.agent import _extract_artifacts
    # info string after the language token (```python title=x) must not drop the block
    a = _extract_artifacts("x:\n```python title=hi\nprint(1)\nprint(2)\n```")
    assert a and a[0]["lang"] == "python" and a[0]["lines"] == 2
    # a max_tokens-truncated (unclosed) trailing block is still extracted, flagged truncated
    b = _extract_artifacts("code:\n```python\nprint(1)\nfor i in range(3):\n    print(i)")
    assert b and b[0].get("truncated") is True


# ── Round 4: stacked labels, assistant role, deliberation single-POV, title parity ──────────────

def test_stacked_double_labels_all_stripped():
    # The model can STACK two leading labels; a single pass leaked the second ("two tags").
    assert strip_junk_from_reply("Layla\nMorrigan\nThe answer is 42.") == "The answer is 42."
    assert strip_junk_from_reply("Nyx\nEcho\nThe answer is 42.") == "The answer is 42."
    assert strip_junk_from_reply("assistant: Morrigan: Here is the fix.") == "Here is the fix."


def test_leading_assistant_label_stripped_but_prose_safe():
    assert strip_junk_from_reply("assistant: the answer is four.") == "the answer is four."
    assert strip_junk_from_reply("Assistant\nHere is the code.") == "Here is the code."
    # bare "Assistant" as a prose word (no colon/newline) must survive
    assert strip_junk_from_reply("Assistant chefs prepare the meal.") == "Assistant chefs prepare the meal."


def test_bare_name_stops_removed_anchored_kept():
    import runtime_safety
    from services.llm import llm_gateway
    ss = llm_gateway.get_stop_sequences()
    assert "\nMorrigan:" in ss and "Morrigan:" not in ss   # anchored kept, bare removed (#5)


def test_deliberation_single_pov_line_does_not_leak():
    import orchestrator
    reply, _ = orchestrator.split_deliberation_output("[" + _SIG + " MORRIGAN] (blunt): only one line", "Morrigan")
    assert not reply.strip()


def test_title_synth_covers_markdown_and_composite_labels():
    from services.agent.title_synthesizer import _clean_title
    assert _clean_title("**Morrigan:** Auth Refactor") == "Auth Refactor"
    assert _clean_title("Layla " + _SIG + " Morrigan: Auth Refactor") == "Auth Refactor"


# ── 4. The reasoning_handler path also strips a leading label (it had none) ─────────────────────

def test_clean_response_text_strips_leading_label():
    assert clean_response_text("Layla: the answer is four.") == "the answer is four."
    assert clean_response_text(_SIG + " Morrigan: the answer is four.") == "the answer is four."


# ── 5. Stop sequences MERGE — built-in anti-leak stops survive an operator override ─────────────

def test_stop_sequences_merge_keeps_builtin_antileak_list(monkeypatch):
    import runtime_safety
    from services.llm import llm_gateway
    _orig = runtime_safety.load_config
    monkeypatch.setattr(runtime_safety, "load_config",
                        lambda: {**_orig(), "stop_sequences": ["\nUser:", " User:"]})
    ss = llm_gateway.get_stop_sequences()
    for must in ("\nMorrigan:", "\nLayla:", "\nNyx:", "\nEris:", "\nCassandra:", "\nLilith:", "## SYSTEM"):
        assert must in ss, must
    # the over-broad generic heading stop (blocked legit markdown headings) is gone
    assert "\n## " not in ss
    # BARE position-0 name stops are gone: they aborted a legitimate short reply at token 0 when the
    # model restated its primed "{name}:" (the leak is instead removed by strip_junk_from_reply).
    for gone in ("Morrigan:", "Layla:", "Nyx:"):
        assert gone not in ss, gone
    # operator custom stop is still honored (union, not replace)
    monkeypatch.setattr(runtime_safety, "load_config",
                        lambda: {**_orig(), "stop_sequences": ["<<CUSTOM_STOP>>"]})
    ss2 = llm_gateway.get_stop_sequences()
    assert "<<CUSTOM_STOP>>" in ss2 and "\nMorrigan:" in ss2


# ── 6. Deliberation: an empty CONCLUSION must NOT promote the raw POV/trace block ───────────────

def test_deliberation_empty_conclusion_does_not_leak_pov_block():
    import orchestrator
    pov = ("[" + _SIG + " MORRIGAN] (blunt): Use a read timeout.\n"
           "[✦ NYX] (layered): Cap retries.\n[CONCLUSION — MORRIGAN]:   ")
    reply, _meta = orchestrator.split_deliberation_output(pov, "Morrigan")
    assert not reply.strip(), f"POV scaffold leaked as reply: {reply!r}"


def test_deliberation_no_marker_still_returns_text():
    import orchestrator
    reply, _ = orchestrator.split_deliberation_output("just a plain answer, no markers", "Morrigan")
    assert reply == "just a plain answer, no markers"


# ── 7. Title synth strips a leaked sigil/name speaker label ─────────────────────────────────────

def test_title_clean_strips_aspect_label():
    from services.agent.title_synthesizer import _clean_title
    assert _clean_title(_SIG + " Morrigan: Auth Refactor") == "Auth Refactor"
    assert _clean_title("Morrigan: Auth Refactor") == "Auth Refactor"
    assert _clean_title("CI Setup Guide") == "CI Setup Guide"          # untouched


# ── 8. Length rule: keeps "Match length" but now permits longer answers when warranted ─────────

def test_length_rule_permits_longer_when_needed():
    from services.prompts.system_head_builder import _OUTPUT_DISCIPLINE as disc
    assert "Match length" in disc                       # short-by-default clause kept
    assert "length follows need" in disc.lower() or "longer when it earns it" in disc.lower()
