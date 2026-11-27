"""Goal-string fallbacks in tool dispatch must mine the operator's message, never Layla's own scaffolding.
Live: list_dir received the path "far]:" lifted from "[Tool results so far]:" in the rebuilt goal."""
import ast
import sys
import types
from pathlib import Path

AGENT_DIR = Path(__file__).resolve().parent.parent
if str(AGENT_DIR) not in sys.path:
    sys.path.insert(0, str(AGENT_DIR))

MSG = "List the files in my workspace."
REBUILT = MSG + "\n\n[Tool results so far]:\nlist_dir: ok=False error=Path not found"


def test_probe_reproduces_the_bad_extraction():
    import agent_loop as al

    assert al._extract_path(REBUILT), "PROBE BROKEN: the rebuilt goal no longer yields a bogus path"
    assert not al._extract_path(MSG)


def test_fallback_uses_the_operator_message():
    import agent_loop as al
    from services.tools.tool_dispatch import _operator_text

    ctx = types.SimpleNamespace(state={"original_goal": MSG})
    assert al._extract_path(_operator_text(ctx, REBUILT)) == ""


def test_no_extraction_fallback_reads_the_raw_goal():
    tree = ast.parse((AGENT_DIR / "services" / "tools" / "tool_dispatch.py").read_text(encoding="utf-8"))
    bad = [n.lineno for n in ast.walk(tree) if isinstance(n, ast.Call)
           and (getattr(n.func, "attr", "") or getattr(n.func, "id", "")).startswith("_extract_")
           and n.args and isinstance(n.args[0], ast.Name) and n.args[0].id == "goal"]
    assert not bad, f"extraction fallback reads the rebuilt goal at lines {bad}"
