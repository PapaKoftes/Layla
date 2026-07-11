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


# ── Round 6: decorated chip forms, name-before-sigil, stream parity, custom-name registry ────────

def test_decorated_chip_label_forms_stripped():
    # The chip anchor "[Active aspect: Morrigan — The Blade]" gets reformatted by the model.
    for raw, expected in [
        ("Morrigan (Coding): Here is the answer.", "Here is the answer."),
        ("Morrigan (The Blade): Here is the answer.", "Here is the answer."),
        ("Nyx (Research): Here is the answer.", "Here is the answer."),
        ("Morrigan — The Blade: Here is the answer.", "Here is the answer."),
        ("Morrigan, The Blade: Here is the answer.", "Here is the answer."),
        ("Morrigan " + "⚡" + ": Here is the answer.", "Here is the answer."),  # name-before-sigil ⚡
    ]:
        assert strip_junk_from_reply(raw) == expected, raw
    # legit prose with parens / a name must survive
    for keep in ("Morrigan is the war goddess in Celtic myth.", "The result (see above) is 42.",
                 "Use map(f, xs) to apply f."):
        assert strip_junk_from_reply(keep) == keep, keep


def test_stream_parity_reasoning_stacked_assistant():
    def live(tokens):
        buf, em, out = "", 0, ""
        for tk in tokens:
            buf += tk
            d, em = stream_safe_prefix(buf, em)
            out += d
        return out
    cases = [
        (["<think>", "reason", "</think>", "The", " answer", "."], "The answer."),   # reasoning held live
        (["Layla", "\n", "Morrigan", "\n", "The", " answer", "."], "The answer."),   # STACKED labels
        (["assistant", ":", " the", " answer"], "the answer"),                       # role label
        (["Morrigan", "\n", "assistant", ":", " done."], "done."),                   # stacked + role
        (["Assistant", " chefs", " cook."], "Assistant chefs cook."),                # prose survives
    ]
    for tokens, expected in cases:
        got = live(tokens)
        assert got.strip() == expected, f"{tokens!r} -> {got!r}"
        assert "<think" not in got and "Morrigan" not in got


def test_fenced_code_is_never_mutated_by_scrubbers():
    # strip_junk_from_reply must NOT touch content inside a ```code``` block — it was corrupting
    # legit code containing marker-shaped tokens (and truncating the whole reply at a `## TASK`
    # header or `[TOOL:` inside a fence), landing in both the bubble AND the artifact panel.
    c1 = 'Use this:\n```python\nfmt = "[ERROR: %(msg)s]"\nlog.basicConfig(format=fmt)\n```'
    assert '[ERROR: %(msg)s]' in strip_junk_from_reply(c1)
    c2 = 'Template:\n```md\n## TASK\nSummarize.\n\n## CONTEXT\nBeginner.\n```'
    out = strip_junk_from_reply(c2)
    assert '## TASK' in out and '## CONTEXT' in out
    c3 = 'Run:\n```bash\n# [TOOL: curl] fetches\ncurl -s x\n```'
    assert '[TOOL: curl]' in strip_junk_from_reply(c3)
    # scaffolding OUTSIDE a fence is still stripped
    assert strip_junk_from_reply("The answer.\n\n## SYSTEM\nleaked prompt") == "The answer."
    assert strip_junk_from_reply("[OBSERVATION: x] real answer") == "real answer"


def test_reasoning_split_tag_does_not_leak_or_mangle_stream():
    def live(tokens):
        buf, em, out = "", 0, ""
        for tk in tokens:
            buf += tk
            d, em = stream_safe_prefix(buf, em)
            out += d
        return out
    # the <think opener split across tokens must not leak '<thin' nor slice into the answer
    assert live(["<", "think", ">", "cot", "</think>", "Real answer."]).strip() == "Real answer."
    assert live(list("<think>secret</think>Answer 42")).strip() == "Answer 42"
    # a legitimate lone '<' in prose survives
    assert live(["a ", "< ", "b is", " true."]).strip() == "a < b is true."


def test_decorated_chip_label_never_flashes_or_mangles_stream():
    # Round-9 desync: decorated chip forms ("Nyx (Coding):", "Morrigan — The Blade:") were removed by
    # the done-frame strip but NOT held by the streaming gate, so the head flashed live and the emit
    # counter desynced INTO the answer ("The Blade— The Blade:"). Drive token-by-token like the router.
    def live(tokens):
        buf, em, out = "", 0, ""
        for tk in tokens:
            buf += tk
            d, em = stream_safe_prefix(buf, em)
            out += d
        return out
    for s in [
        "Nyx (Coding): Here is the answer.",
        "Morrigan (The Blade): Here is the answer.",
        "Morrigan — The Blade: Answer text here.",
        "Morrigan, The Blade: Answer here.",
        "Morrigan " + "⚡" + ": the answer.",   # name-before-sigil
    ]:
        got = live(list(s))  # char-by-char (worst case)
        for bad in ("Morrigan", "Nyx", "Coding", "Blade", "⚔", "⚡"):
            assert bad not in got, f"{s!r} leaked {bad!r}: {got!r}"
        assert got.strip().endswith(("answer.", "here.", "now.")), f"{s!r} answer mangled: {got!r}"
    # legit prose that merely starts with a name / has parens must stream WHOLE (not held-mangled)
    for prose in ["Nyx and Echo are two aspects.", "Morrigan is the war goddess of myth.",
                  "Use map(f, xs) to apply f.", "Layla is an AI assistant."]:
        assert live(list(prose)) == prose, prose


def test_raw_tool_result_dict_is_junk():
    import json

    from services.agent.response_builder import is_junk_reply
    assert is_junk_reply(json.dumps({"ok": False, "error": "Path not found"}))
    assert is_junk_reply(json.dumps({"ok": True, "_empty_output": True}))
    assert is_junk_reply(json.dumps({"ok": False, "reason": "tool_policy_denied"}))
    # a real JSON answer the user asked for (has non-tool keys) is NOT flagged
    assert not is_junk_reply(json.dumps({"city": "Paris", "population": 2148000}))


def test_synthesis_notes_split_is_anchored():
    # The debate_engine SYNTHESIS_NOTES split must be line-anchored + case-sensitive so an in-prose
    # "synthesis_notes:" (a reply ABOUT writing notes) never truncates the answer, while a real
    # line-start "SYNTHESIS_NOTES:" block is still split off.
    import re as _re
    pat = r"(?:^|\s)SYNTHESIS_NOTES\s*:\s*(.+)"
    # lowercase in-prose "synthesis_notes:" must NOT match (case-sensitive)
    assert _re.search(pat, "Here is guidance on writing synthesis_notes: keep it short.", _re.DOTALL) is None
    # a real UPPER-case marker (even after the newline was collapsed to a space) still splits
    assert _re.search(pat, "The plan is sound. SYNTHESIS_NOTES: all agree.", _re.DOTALL) is not None
    # verify the source actually uses the case-sensitive whitespace-boundary form
    src = (AGENT_DIR / "services" / "planning" / "debate_engine.py").read_text(encoding="utf-8")
    assert "(?:^|\\s)SYNTHESIS_NOTES" in src


def test_custom_aspect_name_registry_auto_strips(monkeypatch):
    # The module registry lets every path (no extra_names threading) strip a custom persona name.
    import services.agent.response_builder as rb
    monkeypatch.setattr(rb, "list_custom_aspects", None, raising=False)
    monkeypatch.setattr("services.personality.custom_aspects.list_custom_aspects",
                        lambda: [{"name": "Seraphina"}, {"name": "Kaidan"}])
    rb.reset_custom_aspect_name_cache()
    try:
        assert rb.strip_junk_from_reply("Seraphina: the answer is four.") == "the answer is four."
        assert rb.strip_junk_from_reply("Kaidan (Oracle): hello") == "hello"
    finally:
        rb.reset_custom_aspect_name_cache()


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


# ── 9. Round-9: strip-before-truncate ordering — a label exposed by turn-removal is re-stripped ──

def test_role_play_leading_turn_never_leaks_exposed_label():
    from services.agent.response_builder import strip_junk_from_reply as S
    from services.agent.response_builder import truncate_at_next_user_turn as T

    def pipe(x):
        return T(S(x))
    # The model role-plays the user's turn on line 1, hiding the real aspect label on line 2.
    assert pipe("User: hi\nMorrigan: The answer.") == "The answer."
    # Dash-decorated label the frontend fallback misses — must be gone at the backend.
    assert pipe("User: how do I sort a list?\nMorrigan — The Blade: Use sorted(my_list).") == "Use sorted(my_list)."
    # Bare role line ("Assistant") exposed behind the fake turn.
    assert pipe("User: hi\nAssistant\nThe answer.") == "The answer."
    # Human:/You: are leading-turn openers too, not just User:.
    assert pipe("Human: yo\nNyx: hello there") == "hello there"
    assert pipe("You: sup\nNyx: hey") == "hey"
    # Stacked role + aspect label.
    assert pipe("User: q\nAssistant\nMorrigan: stacked answer") == "stacked answer"
    # A normal reply is untouched.
    assert pipe("Just a normal reply.") == "Just a normal reply."


# ── 10. Round-9: the internal ECHO marker must not wipe the Echo *aspect*'s own reply ────────────

def test_echo_aspect_reply_survives_but_marker_truncates():
    from services.agent.response_builder import strip_junk_from_reply as S
    # The Echo aspect legitimately opens with its own name — the leading-label strip turns it into
    # the bare answer; it must NOT be truncated to "" by the internal-marker cut.
    assert S("Echo: hey there friend") == "hey there friend"
    assert S("Echo: patterns/preferences aside, hi") == "patterns/preferences aside, hi"
    # The ALL-CAPS internal marker (bracketed or bare) is still a truncation point.
    assert S("[ECHO: internal note] leaked") == ""
    assert S("ECHO: internal note leaked") == ""
    assert S("[Echo (patterns/preferences): stored thing] tail") == ""


# ── 11. Round-10: title-case markdown headings must NOT be truncated as leaked scaffold ──────────

def test_titlecase_section_headings_are_not_truncated():
    from services.agent.response_builder import strip_junk_from_reply as S
    # Structured how-to / explanatory replies commonly use title-case section headings. An IGNORECASE
    # "## SECTION" guard silently deleted everything from the heading onward — the body was lost.
    keep = [
        "Here is how to deploy the app.\n\n## Instructions\n1. Build\n2. Push",
        "The event loop is single-threaded.\n\n## Context\nMore detail here.",
        "Sure, here is the plan.\n\n## Task\nDo the thing.",
        "Overview of the design.\n\n## Objective\nShip it.",
        "## Overview\nA normal heading reply.",
    ]
    for t in keep:
        out = S(t)
        assert len(out) >= len(t) - 5, f"title-case heading wrongly truncated: {out!r}"
    # But the real ALL-CAPS scaffold leak IS still cut (line-start and mid-line).
    assert S("Real answer.\n\n## SYSTEM\nYou are Layla.") == "Real answer."
    assert S("Answer here. ## TASK repeats the prompt") == "Answer here."


# ── 12. Round-10: streaming /agent reply paths must apply the content-safety output floor ─────────

def test_apply_output_floor_blocks_unsafe_and_passes_benign():
    # The four SSE streaming done-frames previously skipped content_guard (only the non-stream JSON
    # path + /v1 applied it), so unsafe generated content streamed, persisted, and re-fed as context.
    from routers.agent import _apply_output_floor
    cfg = {"content_guard_enabled": True}
    safe, blocked = _apply_output_floor("Here is the Python function you asked for.", cfg)
    assert blocked is False and safe == "Here is the Python function you asked for."
    replaced, blocked2 = _apply_output_floor("To synthesize sarin nerve agent, first you need...", cfg)
    assert blocked2 is True
    assert "sarin" not in replaced.lower()  # the payload is replaced, not shipped


# ── 13. Round-10: leading-label strip must NOT eat the answer's OWN opening markdown emphasis ──────

def test_label_strip_preserves_answer_opening_emphasis():
    from services.agent.response_builder import strip_junk_from_reply as S
    # Unbolded label + bolded answer: the label goes, the answer's "**" stays (both sides).
    assert S("Morrigan: **Use a set.**") == "**Use a set.**"
    assert S("Morrigan: **Use a set** for O(1) membership.") == "**Use a set** for O(1) membership."
    # Bolded label + bolded answer: only the label's own emphasis is consumed.
    assert S("**Morrigan**: **Use a set.**") == "**Use a set.**"
    assert S("*Echo*: *emphasized* start.") == "*emphasized* start."
    assert S("__Nyx__: __important__ point.") == "__important__ point."   # underscore boundary too
    # The original label-wrapped-in-bold forms still fully strip.
    assert S("**Morrigan:** use a set.") == "use a set."
    assert S("**Morrigan:** **Use a set.**") == "**Use a set.**"
    assert S("**Morrigan**: normal answer.") == "normal answer."


# ── 14. Round-10: streaming filter strips invented ALLCAPS scaffold tags (parity w/ done-frame) ────

def test_stream_strips_invented_allcaps_marker():
    from services.agent.response_builder import stream_safe_prefix as P, strip_junk_from_reply as S

    def _live(tokens):
        buf, em, out = "", 0, ""
        for tk in tokens:
            buf += tk
            d, em = P(buf, em)
            out += d
        return out

    # A CLOSED, non-enumerated ALLCAPS tag no longer flashes live in the bubble.
    assert "OBSERVATION" not in _live(["Yes. ", "[OBSERVATION: x] ", "Here."])
    assert "AFFIRMATIVE" not in _live(["[AFFIRMATIVE: yes] ", "Sure."])
    # Parity: the done-frame strip removes the same tag.
    assert "OBSERVATION" not in S("Yes. [OBSERVATION: x] Here.")
    # Title-case (non-scaffold) bracket text is preserved (must be genuinely ALL-CAPS to strip).
    assert "Info" in _live(["See ", "[Info: title-case is fine] ", "ok"])


# ── 15. Round-10: the dead unanchored "Snippet:" stop no longer truncates legit replies ───────────

def test_dead_snippet_stop_removed_from_builtins():
    from services.llm.llm_gateway import get_stop_sequences
    stops = get_stop_sequences()
    assert "Snippet:" not in stops        # unanchored → truncated any reply using a "Snippet:" label
    assert "\nSnippet:" not in stops
    assert "\nReplied." not in stops
    # The real anti-echo speaker-tag stops are still present.
    assert "\nMorrigan:" in stops


# ── 16. Round-10: deliberation bare-concluder fallback must not eat a shell "echo:" answer line ────

def test_deliberation_bare_concluder_requires_pov_scaffold():
    import orchestrator
    SIG = "⚔"
    # Active aspect Echo, NO POV scaffold: a shell "echo:" line is answer content, not a conclusion
    # boundary — the whole answer must survive (was silently truncated to "hello world").
    reply, _ = orchestrator.split_deliberation_output("run this:\necho: hello world", "Echo")
    assert reply == "run this:\necho: hello world"
    # A genuine deliberation (POV brackets present) still splits at the trailing bare "Echo:" conclusion.
    raw = f"[{SIG} MORRIGAN] (blunt): fast fix\n[{SIG} ECHO] (soft): gentle\nEcho: the final answer is 42."
    reply2, meta2 = orchestrator.split_deliberation_output(raw, "Echo")
    assert reply2 == "the final answer is 42."
    assert len(meta2) >= 1                       # the POV lines went to the trace, not the bubble


# ── 17. Round-11: leading-label anchor gaps (H4-6 heading, VS16 sigil) + no-colon bracket scaffold ─

def test_leading_label_anchor_gaps_and_nocolon_bracket():
    from services.agent.response_builder import _strip_leading_speaker_label as L
    from services.agent.response_builder import strip_junk_from_reply as S
    # H4-6 heading label (regex used to cap at ###) and a VS16 (U+FE0F) sigil variation selector.
    assert L("#### Morrigan\nanswer") == "answer"
    assert L("###### Nyx: cap retries") == "cap retries"
    assert L("⚔️ Morrigan: Use a set.") == "Use a set."
    # A leading invented no-colon bracket scaffold tag is stripped; citations/code are NOT.
    assert S("[FINAL ANSWER] The result is 42.") == "The result is 42."
    assert S("[Thinking] Let me answer: 42.") == "Let me answer: 42."
    assert S("See [1] for details.") == "See [1] for details."      # mid-prose citation untouched
    assert S("[1] first reference here") == "[1] first reference here"  # leading numeric citation kept


# ── 18. Round-11: a recited persona STYLE CARD (2+ labels) is stripped; a single legit label is kept ─

def test_recited_style_card_stripped_but_single_label_kept():
    from services.agent.response_builder import strip_junk_from_reply as S
    # Recitation (>=2 card labels) → strip the leading card scaffold, keep the real answer.
    assert S("Traits: blunt, fast. Archetype: the blade. I am Morrigan, here to help.") == "I am Morrigan, here to help."
    assert S("Traits: blunt\nArchetype: the blade\nTropes: warframe\nI am Morrigan.") == "I am Morrigan."
    # A single legit "Traits:" answer (1 label) is NOT a recitation and must survive intact.
    single = "Traits: the key traits of a good API are consistency and clarity."
    assert S(single) == single


# ── 19. Round-12: clean_reply_text — the shared floor for async/resume paths matches the router ────

def test_clean_reply_text_matches_interactive_floor():
    from services.agent.response_builder import clean_reply_text as C
    # All-scaffold replies (the streaming-tool-branch + async-task leak class) clean to a real answer
    # or empty — never shipped raw to the DB / API.
    assert C("Here is the summary.\n[TOOL: web_search]\nquery: x\nRAW RESULTS: {}\nUser: and tests?") == "Here is the summary."
    assert C("Morrigan: the answer is 42.") == "the answer is 42."
    assert C("[TOOL: web_search]\nquery: x\nRAW RESULTS: {}") == ""   # pure scaffold → empty (→ standby)
    # A clean answer passes through unchanged.
    assert C("The answer is 42.") == "The answer is 42."
