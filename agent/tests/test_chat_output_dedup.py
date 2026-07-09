"""Regression guards for the chat output/deliberation bugs (multi-response, dup code, aspect tags).

Covers:
- deliberation (the 6-aspect debate that reads as ~6 stitched answers) is OFF by default;
- bracketed aspect scaffold tags never survive into a reply;
- an exact reprinted code block is collapsed, but distinct blocks are preserved;
- polish_output collapses a duplicated code block even on the None-cfg branch.
"""
import sys
from pathlib import Path

AGENT_DIR = Path(__file__).resolve().parent.parent
if str(AGENT_DIR) not in sys.path:
    sys.path.insert(0, str(AGENT_DIR))


class TestDeliberationOffByDefault:
    def test_should_deliberate_false_without_flag(self, monkeypatch):
        import orchestrator
        import runtime_safety
        monkeypatch.setattr(runtime_safety, "load_config", lambda: {})  # no flag => default off
        # Even a phrasing that used to trigger it must not deliberate unless explicitly enabled.
        assert orchestrator.should_deliberate("what do you think I should do?", None) is False
        assert orchestrator.should_deliberate("who are you", None) is False

    def test_schema_default_deliberation_off(self):
        # The shipped default must have deliberation OFF so a fresh install is single-voice.
        import config_schema
        entry = next((f for f in config_schema.EDITABLE_SCHEMA if f["key"] == "deliberation_enabled"), None)
        assert entry is not None and entry.get("default") is False

    def test_should_deliberate_respects_flag(self, monkeypatch):
        import orchestrator
        import runtime_safety
        monkeypatch.setattr(runtime_safety, "load_config", lambda: {"deliberation_enabled": True})
        # With the flag on, a deliberation phrase triggers it again.
        assert orchestrator.should_deliberate("what do you think about this?", None) is True


class TestThinkingModeDeliberation:
    """Thinking mode = one multi-POV pass → single synthesized reply + collapsible trace.
    The old bug streamed all six "[⚔ MORRIGAN] …" POV lines into the reply body."""

    _RAW = (
        "[⚔ MORRIGAN] (blunt): Use a read timeout.\n"
        "[✦ NYX] (layered): Cap the retry loop too.\n"
        "[◎ ECHO] (reflective): Same bug as last week.\n"
        "[⚡ ERIS] (sideways): or just fail fast.\n"
        "[⌖ CASSANDRA] (immediate): it is the timeout.\n"
        "[⊛ LILITH] (honest): no deadline is set anywhere.\n"
        "[CONCLUSION — MORRIGAN]: Add a read timeout and cap the retry loop."
    )

    def test_split_reply_is_conclusion_only(self):
        import orchestrator
        reply, resp = orchestrator.split_deliberation_output(self._RAW, "Morrigan")
        # the reply the user sees is ONLY the synthesized conclusion …
        assert reply == "Add a read timeout and cap the retry loop."
        # … with no aspect tags, names, or POV text leaking in
        for leak in ("MORRIGAN", "NYX", "[", "fail fast", "last week"):
            assert leak not in reply
        # … and every POV becomes a trace entry keyed by aspect id
        assert set(resp) == {"morrigan", "nyx", "echo", "eris", "cassandra", "lilith"}
        assert "read timeout" in resp["morrigan"] and "deadline" in resp["lilith"]

    def test_split_fallback_no_marker(self):
        import orchestrator
        # no CONCLUSION marker => whole thing is the reply, empty trace (never crashes)
        reply, resp = orchestrator.split_deliberation_output("plain answer, no markers", "Morrigan")
        assert reply == "plain answer, no markers" and resp == {}

    def test_show_thinking_dispatches_to_deliberation(self, monkeypatch):
        # show_thinking must run the deliberation pass: exactly one trace-meta frame,
        # reply = conclusion, POV text never in the reply body.
        import json as _json

        import services.agent.stream_handler as sh
        import services.llm.llm_gateway as gw
        raw = self._RAW

        def _fake(prompt, **kw):
            for i in range(0, len(raw), 40):
                yield raw[i:i + 40]

        monkeypatch.setattr(gw, "run_completion", _fake)
        frames = list(sh.stream_reason("why does it hang?", show_thinking=True, aspect_id="morrigan"))
        metas = [f for f in frames if isinstance(f, str) and f.startswith("__DELIB_META__")]
        reply = "".join(f for f in frames if isinstance(f, str) and not f.startswith("__DELIB_META__"))
        assert len(metas) == 1
        meta = _json.loads(metas[0].split("__DELIB_META__")[1].split("__DELIB_END__")[0])
        assert meta["mode"] == "tribunal"
        assert set(meta["aspect_responses"]) == {"morrigan", "nyx", "echo", "eris", "cassandra", "lilith"}
        assert "Add a read timeout" in reply
        for leak in ("MORRIGAN", "[", "fail fast"):
            assert leak not in reply


class TestPhaticReplyLengthCap:
    """A phatic turn ('hi') gets a short, warm reply — generation is capped hard so the
    small model can't ramble/drift. Substantive short questions keep the full budget."""

    def _record_max_tokens(self, monkeypatch, goal):
        import services.agent.stream_handler as sh
        import services.llm.llm_gateway as gw
        seen = {}

        def _fake(prompt, **kw):
            seen["max_tokens"] = kw.get("max_tokens")
            yield "ok."

        monkeypatch.setattr(gw, "run_completion", _fake)
        # light mode = the fast/phatic path; is_lightweight_chat_turn only fires there
        list(sh.stream_reason(goal, reasoning_mode_override="light", aspect_id="morrigan"))
        return seen.get("max_tokens")

    def test_phatic_turn_is_capped(self, monkeypatch):
        cap = self._record_max_tokens(monkeypatch, "hi")
        assert cap is not None and cap <= 80, f"phatic reply should be capped, got {cap}"

    def test_substantive_short_question_keeps_budget(self, monkeypatch):
        # 'who are you' is short but substantive → NOT lightweight → full budget (> the cap)
        cap = self._record_max_tokens(monkeypatch, "who are you?")
        assert cap is not None and cap > 80, f"substantive turn must keep full budget, got {cap}"


class TestAspectTagStripping:
    def test_bracketed_aspect_tags_removed(self):
        from services.agent.response_builder import strip_junk_from_reply
        out = strip_junk_from_reply("[⚔ MORRIGAN] one\n[✦ NYX] two\n[CONCLUSION — MORRIGAN]: hi")
        for name in ("MORRIGAN", "NYX", "ERIS", "CASSANDRA", "LILITH"):
            assert name not in out

    def test_stream_marker_re_covers_aspect_names(self):
        from services.agent import response_builder as rb
        assert rb._STREAM_MARKER_RE.search("[⚔ MORRIGAN]")
        assert rb._STREAM_MARKER_RE.search("[✦ NYX] hello")

    def test_invented_allcaps_marker_stripped(self):
        from services.agent.response_builder import strip_junk_from_reply
        # a small model invents "[AFFIRMATIVE: …]" style scaffold — must be stripped.
        assert "AFFIRMATIVE" not in strip_junk_from_reply("Sup. [AFFIRMATIVE: if user is rude]")

    def test_allcaps_marker_strip_is_code_safe(self):
        from services.agent.response_builder import strip_junk_from_reply
        # colon-required + case-sensitive: array/dict access and log levels must survive.
        out = strip_junk_from_reply("Use dict[KEY] and arr[IDX]. Log [ERROR] ref [1].")
        for keep in ("dict[KEY]", "arr[IDX]", "[ERROR]", "[1]"):
            assert keep in out

    def test_trailing_selfname_echo_stripped(self):
        from services.agent.response_builder import strip_junk_from_reply
        assert strip_junk_from_reply("Let your journey begin. Layla. Hello.") == "Let your journey begin."
        # a name used mid-sentence / in code must NOT be stripped
        assert "Layla.process()" in strip_junk_from_reply("Call Layla.process() to start.")
        assert strip_junk_from_reply("The capital is Paris.") == "The capital is Paris."

    def test_midline_prompt_section_echo_stripped(self):
        # A small model can echo a scaffold header MID-LINE then repeat itself:
        # "… here?  ## SYSTEM\n\n<repeats the prompt>". Everything from the ALL-CAPS section
        # name on is leaked scaffolding and must be cut (the line-anchored strippers miss it).
        from services.agent.response_builder import strip_junk_from_reply
        live = "How can I assist you today? What brings you here?  ## SYSTEM\n\nHow can I assist you today?"
        out = strip_junk_from_reply(live)
        assert "SYSTEM" not in out and "##" not in out
        assert out.endswith("What brings you here?")
        for scaffold in ("Done. ## TASK\n\nx", "Sure! ## OBJECTIVE echo", "ok ## CONTEXT dump"):
            assert "##" not in strip_junk_from_reply(scaffold)
        # case-SENSITIVE: title-case markdown + the plain words must survive untouched
        assert "Context matters" in strip_junk_from_reply("The answer is 42 ## Context matters here.")
        assert "operating system" in strip_junk_from_reply("The operating system boots fast.")


class TestPromptHygiene:
    def test_internal_identity_keys_not_injected(self):
        # interaction_history_* (recent_tools JSON) + maturity/stat/tutorial state must never
        # be dumped into the prompt as "User/companion context".
        import orchestrator
        from layla.memory.user_profile import set_user_identity
        from services.prompts.system_head_builder import build_system_head
        set_user_identity("interaction_history_morrigan", '{"recent_tools":["read_file"],"total_interactions":9}')
        set_user_identity("formality", "casual")
        asp = orchestrator.select_aspect("Hello", force_aspect="morrigan")
        head = build_system_head(goal="Hello", aspect=asp, reasoning_mode="light")
        assert "recent_tools" not in head
        assert "interaction_history" not in head

    def test_no_reference_docs_on_lightweight_turn(self):
        import orchestrator
        from services.prompts.system_head_builder import build_system_head
        asp = orchestrator.select_aspect("hi", force_aspect="morrigan")
        head = build_system_head(goal="hi", aspect=asp, reasoning_mode="light")
        assert "Reference docs" not in head


class TestDuplicateBlockCollapse:
    _DUP = "Here is the script:\n```bash\nssh user@host\n```\nRemember to replace it.\n```bash\nssh user@host\n```"
    _DISTINCT = "```bash\npip install x\n```\nthen\n```bash\npip install y\n```"

    def test_reprinted_block_collapsed(self):
        from services.agent.response_builder import _collapse_duplicate_blocks
        out = _collapse_duplicate_blocks(self._DUP)
        assert out.count("ssh user@host") == 1
        assert out.count("```") == 2  # exactly one fenced block remains

    def test_distinct_blocks_preserved(self):
        from services.agent.response_builder import _collapse_duplicate_blocks
        out = _collapse_duplicate_blocks(self._DISTINCT)
        assert out.count("```") == 4  # both blocks kept
        assert "pip install x" in out and "pip install y" in out

    def test_polish_output_collapses_with_and_without_cfg(self):
        from services.infrastructure.output_polish import polish_output
        assert polish_output(self._DUP, {"output_quality_gate_enabled": True}).count("ssh user@host") == 1
        # the None-cfg passthrough branch must ALSO dedupe (guards the bypass).
        assert polish_output(self._DUP, None).count("ssh user@host") == 1


class TestStreamMainPathHasFilter:
    def test_main_stream_uses_stream_safe_prefix(self):
        # Guard: the main streaming path must filter tokens (not yield raw), like the fast path.
        src = (AGENT_DIR / "routers" / "agent.py").read_text(encoding="utf-8", errors="replace")
        assert "stream_safe_prefix" in src
        # the raw-token yield that flashed aspect tags must be gone
        assert "yield f\"data: {json.dumps({'token': token})}\\n\\n\"" not in src
