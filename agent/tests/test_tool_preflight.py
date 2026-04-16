"""
Tests for tool-argument preflight.
"""
import sys
from pathlib import Path

AGENT_DIR = Path(__file__).resolve().parent.parent
if str(AGENT_DIR) not in sys.path:
    sys.path.insert(0, str(AGENT_DIR))


def test_preflight_blocks_read_file_without_path():
    from services.tool_preflight import preflight_tool

    pf = preflight_tool("read_file", {"args": {}}, "please read the file", "")
    assert pf.ok is False
    assert "path" in (pf.reason or "").lower()


def test_preflight_blocks_fetch_url_without_url():
    from services.tool_preflight import preflight_tool

    pf = preflight_tool("fetch_url", {"args": {}}, "fetch it", "")
    assert pf.ok is False
    assert "url" in (pf.reason or "").lower()


def test_preflight_allows_read_file_with_args():
    from services.tool_preflight import preflight_tool

    pf = preflight_tool("read_file", {"args": {"path": "agent/main.py"}}, "read agent/main.py", "")
    assert pf.ok is True
