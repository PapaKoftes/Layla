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
