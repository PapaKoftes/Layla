"""Explicit "create file X" requests force write_file as the first decision; everything else is untouched.
See services/agent/forced_tool.py for the measurement that motivated it."""
import sys
from pathlib import Path

import pytest

AGENT_DIR = Path(__file__).resolve().parent.parent
if str(AGENT_DIR) not in sys.path:
    sys.path.insert(0, str(AGENT_DIR))

from services.agent.forced_tool import forced_first_tool  # noqa: E402

TOOLS = frozenset({"read_file", "write_file", "list_dir"})

FIRES = [
    "Create a file named notes_a.txt in the workspace containing exactly the word banana.",
    "Write 'hello world' to a new file hello.txt.",
    "Make a file called todo.md with one line: call mom.",
    "Save this shopping list to shopping.md: eggs, milk, bread.",
    "Can you create notes/plan.md with three headings?",
]
NEVER = [
    "How do I create a file in Python?",                       # question
    "What does probe_token.txt say?",                          # read
    "Read a.txt and write a summary to b.md",                  # read first + two files
    "Summarize report.md into summary.md",                     # read first
    "Write a python script that sorts a list",                 # no filename
    "Fix the typo in README.md",                               # edit = read first
    "Save https://example.com/page.html for later",            # URL is not a filename
    "Hey, how's it going?",
]


@pytest.fixture(autouse=True)
def _empty_default_sandbox(tmp_path_factory, monkeypatch):
    """No workspace on a request means the default sandbox; keep it empty here so this box's real one (which
    may hold a probe_token.txt) never decides a test."""
    from layla.tools import sandbox_core

    empty = tmp_path_factory.mktemp("default_sandbox")
    monkeypatch.setattr(sandbox_core, "_get_sandbox", lambda: empty)


@pytest.mark.parametrize("msg", FIRES)
def test_fires_on_explicit_create_requests(msg):
    assert forced_first_tool(msg, allow_write=True, valid_tools=TOOLS, steps=[]) == "write_file"


@pytest.mark.parametrize("msg", NEVER)
def test_never_fires_otherwise(msg):
    assert forced_first_tool(msg, allow_write=True, valid_tools=TOOLS, steps=[]) is None


def test_requires_allow_write_offer_and_first_step():
    m = FIRES[0]
    assert forced_first_tool(m, allow_write=False, valid_tools=TOOLS, steps=[]) is None
    assert forced_first_tool(m, allow_write=True, valid_tools=frozenset({"read_file"}), steps=[]) is None
    assert forced_first_tool(m, allow_write=True, valid_tools=TOOLS, steps=[{"action": "pre_read_probe"}]) == "write_file"
    assert forced_first_tool(m, allow_write=True, valid_tools=TOOLS, steps=[{"action": "write_file"}]) is None
    assert forced_first_tool(m, allow_write=True, valid_tools=TOOLS, steps=[{"action": "list_dir"}]) is None


def test_named_existing_file_forces_a_read(tmp_path):
    (tmp_path / "probe_token.txt").write_text("x", encoding="utf-8")
    ws = str(tmp_path)
    for msg in ("What is the secret token in probe_token.txt?", "Fix the typo in probe_token.txt"):
        assert forced_first_tool(msg, allow_write=False, valid_tools=TOOLS, steps=[], workspace_root=ws) == "read_file", msg
    # not existing, not in the (empty) default sandbox, two files, or not first step -> no forcing
    assert forced_first_tool("What is in missing.txt?", allow_write=False, valid_tools=TOOLS, steps=[], workspace_root=ws) is None
    assert forced_first_tool("What is in probe_token.txt?", allow_write=False, valid_tools=TOOLS, steps=[]) is None
    assert forced_first_tool("Compare probe_token.txt and a.md", allow_write=False, valid_tools=TOOLS, steps=[], workspace_root=ws) is None
    assert forced_first_tool("What is in probe_token.txt?", allow_write=False, valid_tools=TOOLS,
                             steps=[{"action": "read_file"}], workspace_root=ws) is None
    # escaping the workspace is never "existing in the workspace"
    assert forced_first_tool("Read ../outside.txt", allow_write=False, valid_tools=TOOLS, steps=[], workspace_root=ws) is None


def test_write_wins_over_read_for_an_explicit_create(tmp_path):
    (tmp_path / "notes.txt").write_text("old", encoding="utf-8")
    msg = "Create a file named notes.txt containing banana."
    assert forced_first_tool(msg, allow_write=True, valid_tools=TOOLS, steps=[], workspace_root=str(tmp_path)) == "write_file"


def test_forced_grammar_only_allows_that_tool():
    from services.llm.gbnf_grammar import build_forced_tool_grammar

    g = build_forced_tool_grammar("write_file")
    root = g.splitlines()[0]
    assert '"\\"tool\\""' in root and "write_file" in root and '"\\"args\\"" ws ":" ws object' in root
    assert "reason" not in root and "think" not in root
    llama_cpp = pytest.importorskip("llama_cpp")
    llama_cpp.LlamaGrammar.from_string(g, verbose=False)


def test_decision_loop_hands_allow_write_to_the_decision():
    import ast

    src = (AGENT_DIR / "services" / "agent" / "decision_loop.py").read_text(encoding="utf-8")
    assert any(isinstance(n, ast.Assign) and ast.unparse(n.targets[0]) == "state['_allow_write']"
               for n in ast.walk(ast.parse(src))), "decision_loop must expose allow_write to llm_decision"
    dsrc = (AGENT_DIR / "services" / "agent" / "llm_decision.py").read_text(encoding="utf-8")
    assert "force_tool=_force" in dsrc and "forced_first_tool(" in dsrc


def test_no_workspace_on_the_request_means_the_default_sandbox(tmp_path, monkeypatch):
    """The web UI sends no workspace_root; live, the forced read then never fired and the token was invented."""
    from layla.tools import sandbox_core
    from services.agent.forced_tool import forced_first_tool

    (tmp_path / "probe_token.txt").write_text("The secret token is TOK-1", encoding="utf-8")
    monkeypatch.setattr(sandbox_core, "_get_sandbox", lambda: tmp_path)
    msg = "What is the secret token in probe_token.txt?"
    assert forced_first_tool(msg, allow_write=False, valid_tools=TOOLS, steps=[], workspace_root="") == "read_file"
    assert forced_first_tool("What is in missing.txt?", allow_write=False, valid_tools=TOOLS, steps=[],
                             workspace_root="") is None
