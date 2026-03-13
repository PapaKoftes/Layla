"""Tests for _extract_json_block in research_utils."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from research_utils import _extract_json_block, normalize_stage_text


class TestExtractJsonBlock:
    def test_fenced_json(self):
        text = '```json\n{"action": "tool", "tool": "read_file"}\n```'
        result = _extract_json_block(text)
        assert result == {"action": "tool", "tool": "read_file"}

    def test_fenced_no_lang(self):
        text = '```\n{"key": "value"}\n```'
        result = _extract_json_block(text)
        assert result == {"key": "value"}

    def test_bare_json(self):
        text = '{"action": "reason", "objective_complete": true}'
        result = _extract_json_block(text)
        assert result == {"action": "reason", "objective_complete": True}

    def test_json_embedded_in_text(self):
        text = 'Some reasoning here.\n{"action": "tool", "tool": "list_dir"}\nTrailing text.'
        result = _extract_json_block(text)
        assert result is not None
        assert result["action"] == "tool"

    def test_empty_string(self):
        assert _extract_json_block("") is None

    def test_none_input(self):
        assert _extract_json_block(None) is None

    def test_invalid_json_fenced(self):
        text = '```json\n{"broken: no quote}\n```'
        result = _extract_json_block(text)
        assert result is None

    def test_nested_json(self):
        text = '{"action": "tool", "args": {"path": "/tmp/foo"}}'
        result = _extract_json_block(text)
        assert result is not None
        assert result["args"]["path"] == "/tmp/foo"


class TestNormalizeStageText:
    def test_em_dash(self):
        assert normalize_stage_text("a\u2014b") == "a-b"

    def test_en_dash(self):
        assert normalize_stage_text("a\u2013b") == "a-b"

    def test_no_dash(self):
        assert normalize_stage_text("hello world") == "hello world"

    def test_empty(self):
        assert normalize_stage_text("") == ""

    def test_none(self):
        assert normalize_stage_text(None) == ""
