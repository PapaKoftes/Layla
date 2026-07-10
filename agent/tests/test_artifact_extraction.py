# -*- coding: utf-8 -*-
"""
test_artifact_extraction.py — Tests for server-side artifact extraction (Item #11)

Covers _extract_artifacts() helper in routers/agent.py.

Run:
    cd agent/ && python -m pytest tests/test_artifact_extraction.py -v
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

AGENT_DIR = Path(__file__).resolve().parent.parent
if str(AGENT_DIR) not in sys.path:
    sys.path.insert(0, str(AGENT_DIR))

from routers.agent import _extract_artifacts

# ---------------------------------------------------------------------------
# Basic extraction
# ---------------------------------------------------------------------------

class TestExtractArtifacts:
    def test_empty_string_returns_empty(self):
        assert _extract_artifacts("") == []

    def test_none_like_empty_returns_empty(self):
        assert _extract_artifacts(None) == []  # type: ignore[arg-type]

    def test_no_code_blocks_returns_empty(self):
        assert _extract_artifacts("Hello world, no code here.") == []

    def test_single_python_block(self):
        text = "Here:\n```python\ndef foo():\n    return 42\n```"
        arts = _extract_artifacts(text)
        assert len(arts) == 1
        assert arts[0]["lang"] == "python"
        assert "def foo" in arts[0]["content"]

    def test_lang_extracted(self):
        text = "```javascript\nconsole.log('hi');\nconsole.log('world');\n```"
        arts = _extract_artifacts(text)
        assert arts[0]["lang"] == "javascript"

    def test_no_lang_defaults_to_text(self):
        text = "```\nline one\nline two\n```"
        arts = _extract_artifacts(text)
        assert arts[0]["lang"] == "text"

    def test_multiple_blocks_extracted(self):
        text = (
            "```python\ndef a():\n    pass\n```\n"
            "some prose\n"
            "```bash\necho hello\necho world\n```"
        )
        arts = _extract_artifacts(text)
        assert len(arts) == 2
        langs = {a["lang"] for a in arts}
        assert "python" in langs
        assert "bash" in langs

    def test_one_liner_skipped(self):
        # Single-line code blocks (trivial) should not appear
        text = "```python\npass\n```"
        arts = _extract_artifacts(text)
        assert len(arts) == 0

    def test_two_line_minimum_included(self):
        text = "```python\nline1\nline2\n```"
        arts = _extract_artifacts(text)
        assert len(arts) == 1

    def test_artifact_has_id_field(self):
        text = "```python\ndef foo():\n    return 1\n```"
        arts = _extract_artifacts(text)
        assert "id" in arts[0]
        assert arts[0]["id"].startswith("art_")

    def test_artifact_has_lines_field(self):
        text = "```python\ndef foo():\n    return 1\n    pass\n```"
        arts = _extract_artifacts(text)
        assert arts[0]["lines"] >= 3

    def test_id_is_deterministic(self):
        text = "```python\ndef foo():\n    return 1\n```"
        arts1 = _extract_artifacts(text)
        arts2 = _extract_artifacts(text)
        assert arts1[0]["id"] == arts2[0]["id"]

    def test_different_content_different_id(self):
        t1 = "```python\ndef foo():\n    return 1\n```"
        t2 = "```python\ndef bar():\n    return 2\n```"
        id1 = _extract_artifacts(t1)[0]["id"]
        id2 = _extract_artifacts(t2)[0]["id"]
        assert id1 != id2

    def test_caps_at_20(self):
        # Generate 25 distinct code blocks
        blocks = "\n".join(
            f"```python\ndef f{i}():\n    return {i}\n```" for i in range(25)
        )
        arts = _extract_artifacts(blocks)
        assert len(arts) <= 20

    def test_content_preserved(self):
        code = "def foo():\n    x = 1\n    return x\n"
        text = f"```python\n{code}```"
        arts = _extract_artifacts(text)
        assert arts[0]["content"] == code

    def test_empty_block_skipped(self):
        text = "```python\n   \n```"
        arts = _extract_artifacts(text)
        assert len(arts) == 0

    def test_mixed_content_with_code(self):
        text = (
            "Here is the solution:\n\n"
            "```python\nimport os\n\ndef main():\n    print(os.getcwd())\n```\n\n"
            "This reads the current directory."
        )
        arts = _extract_artifacts(text)
        assert len(arts) == 1
        assert arts[0]["lang"] == "python"

    def test_sql_block(self):
        text = "```sql\nSELECT *\nFROM users\nWHERE active = 1;\n```"
        arts = _extract_artifacts(text)
        assert arts[0]["lang"] == "sql"

    def test_json_block(self):
        text = '```json\n{\n  "key": "value",\n  "num": 42\n}\n```'
        arts = _extract_artifacts(text)
        assert arts[0]["lang"] == "json"

    # ── Round-9: info-string / truncated / tilde fences (the client used to silently drop these) ──

    def test_info_string_fence_lang_is_first_token(self):
        # A fence carrying an info string ("```python title=x") must still yield lang="python".
        arts = _extract_artifacts("```python title=example.py\nprint('a')\nprint('b')\n```")
        assert len(arts) == 1
        assert arts[0]["lang"] == "python"

    def test_unclosed_block_flagged_truncated(self):
        # A reply cut at max_tokens before the closing fence still yields the block, flagged truncated.
        arts = _extract_artifacts("```python\nprint(1)\nprint(2)\nprint(3)")
        assert len(arts) == 1
        assert arts[0].get("truncated") is True

    def test_tilde_fence_supported(self):
        arts = _extract_artifacts("~~~python\nprint(1)\nprint(2)\n~~~")
        assert len(arts) == 1
        assert arts[0]["lang"] == "python"
        assert "truncated" not in arts[0]

    def test_tilde_close_does_not_pair_with_backtick_open(self):
        # A backtick-opened block must not be closed by a stray ~~~ line (and vice-versa).
        arts = _extract_artifacts("```python\nprint(1)\nprint(2)\n~~~\nprint(3)\n```")
        assert len(arts) == 1
        assert "print(3)" in arts[0]["content"]
