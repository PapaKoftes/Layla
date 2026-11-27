"""Every *AGENT_DIR / *REPO_ROOT computed from __file__ resolves to the real directory.

Three modules under agent/services/<pkg>/ used parent.parent (= agent/services) as "agent dir": mDNS kept its
instance id in a stray agent/services/.governance and announced version 0.0.0 forever (it read a VERSION
file that exists nowhere), and the KB builder wrote to an undocumented agent/services/knowledge/_generated.
"""
import ast
from pathlib import Path

AGENT_DIR = Path(__file__).resolve().parent.parent
REPO_ROOT = AGENT_DIR.parent


def _parent_depth(node: ast.AST) -> int | None:
    """Depth of a `Path(__file__).resolve().parent.parent...` / `.parents[n]` chain, else None."""
    depth = 0
    while True:
        if isinstance(node, ast.Attribute) and node.attr == "parent":
            depth += 1
            node = node.value
        elif (isinstance(node, ast.Subscript) and isinstance(node.value, ast.Attribute)
              and node.value.attr == "parents" and isinstance(node.slice, ast.Constant)):
            depth += int(node.slice.value) + 1
            node = node.value.value
        else:
            break
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "resolve":
        node = node.func.value
    if (isinstance(node, ast.Call) and getattr(node.func, "id", None) == "Path" and node.args
            and getattr(node.args[0], "id", None) == "__file__"):
        return depth
    return None


def test_agent_and_repo_dir_constants_point_at_the_right_directory():
    checked, wrong = 0, []
    for py in AGENT_DIR.rglob("*.py"):
        if any(part in {"tests", ".venv", "venv", "__pycache__", "node_modules"} for part in py.parts):
            continue
        try:
            tree = ast.parse(py.read_text(encoding="utf-8"))
        except (SyntaxError, UnicodeDecodeError):
            continue
        for node in ast.walk(tree):
            if not (isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name)):
                continue
            name = node.targets[0].id.upper()
            want = AGENT_DIR if "AGENT_DIR" in name else REPO_ROOT if "REPO_ROOT" in name else None
            depth = _parent_depth(node.value)
            if want is None or depth is None:
                continue
            checked += 1
            got = py.resolve()
            for _ in range(depth):
                got = got.parent
            if got != want:
                wrong.append(f"{py.relative_to(AGENT_DIR)}:{node.lineno} {node.targets[0].id} -> {got}")
    assert checked >= 5, f"PROBE BROKEN: only {checked} dir constants found"
    assert not wrong, "\n".join(wrong)
