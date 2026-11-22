"""Mutable runtime state must not be written inside a read-only install tree.

On an installed build the app lives in C:\\Program Files\\Layla, which a normal user can't write. State that
historically lived beside the code (agent/.governance approvals + audit, .research_lab sandbox, cluster
config, browser screenshots, workspace index, skill packs, conversation history...) therefore failed on
every real install while the source-checkout CI stayed green — the approval queue raised instead of queuing.
runtime_safety.install_state_path() is the single owner: identity on a source checkout, per-user
``<LAYLA_DATA_DIR>/install_state/<same relative layout>`` on an installed build (installer payload marker).

The real-installer proof is installer/clean_install_test.ps1 (approval queued + listed on a clean VM). These
tests pin the mapping, the single-owner invariants, and an AST guard so new code can't regress it.
"""
import ast
import sys
from pathlib import Path

AGENT_DIR = Path(__file__).resolve().parent.parent
if str(AGENT_DIR) not in sys.path:
    sys.path.insert(0, str(AGENT_DIR))

# Path components that are mutable state and historically lived inside the install tree.
STATE_NAMES = {
    ".governance", ".research_lab", ".research_brain", ".research_output", "research_missions",
    "cluster_config.json", "conversation_history.json", "skill_packs_installed", ".screenshots",
    ".browser_profiles", "chroma_db",
}
# (file, enclosing function) -> why it's fine without install_state_path.
ALLOWED = {
    ("layla/memory/vector_store.py", "_chroma_path"):
        "uses <LAYLA_DATA_DIR>/chroma_db when set; the agent-dir fallback only runs when no data dir exists",
}


def _scan(root: Path) -> tuple[list[str], int]:
    """Return (unwrapped state-path constructions, count of wrapped ones)."""
    bad, wrapped = [], 0
    for f in root.rglob("*.py"):
        rel = f.relative_to(root).as_posix()
        if rel.startswith(("tests/", "scripts/")) or "__pycache__" in rel or "/.venv" in f"/{rel}":
            continue
        try:
            tree = ast.parse(f.read_text(encoding="utf-8-sig"))
        except SyntaxError:
            continue
        parents = {c: n for n in ast.walk(tree) for c in ast.iter_child_nodes(n)}
        for n in ast.walk(tree):
            if not (isinstance(n, ast.BinOp) and isinstance(n.op, ast.Div)
                    and isinstance(n.right, ast.Constant) and n.right.value in STATE_NAMES):
                continue
            a, ok, func = n, False, None
            while a in parents:
                a = parents[a]
                if isinstance(a, ast.Call):
                    fn = a.func
                    if (fn.id if isinstance(fn, ast.Name) else getattr(fn, "attr", "")) == "install_state_path":
                        ok = True
                if func is None and isinstance(a, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    func = a.name
            if ok:
                wrapped += 1
            elif (rel, func) not in ALLOWED:
                bad.append(f"{rel}:{n.lineno} builds .../{n.right.value!r} without install_state_path()")
    return bad, wrapped


def test_no_state_path_bypasses_install_state_path():
    bad, wrapped = _scan(AGENT_DIR)
    assert wrapped >= 15, f"PROBE BROKEN: only {wrapped} wrapped state paths seen - the scanner isn't reading the code"
    assert not bad, "state written inside the install tree fails on a real install:\n" + "\n".join(bad)


def test_scanner_catches_an_unwrapped_path(tmp_path):
    (tmp_path / "mod.py").write_text(
        "from pathlib import Path\nfrom runtime_safety import install_state_path\n"
        "OK = install_state_path(Path('x') / '.governance')\nBAD = Path('x') / '.research_lab'\n",
        encoding="utf-8")
    bad, wrapped = _scan(tmp_path)
    assert wrapped == 1 and len(bad) == 1 and "'.research_lab'" in bad[0], (bad, wrapped)


def test_mapping_on_an_installed_build(monkeypatch, tmp_path):
    import runtime_safety as rs

    monkeypatch.setenv("LAYLA_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setattr(rs, "_INSTALLED", True)
    got = rs.install_state_path(rs.AGENT_DIR / ".governance")
    assert got == (tmp_path / "data").resolve() / "install_state" / "agent" / ".governance"
    assert rs.install_state_path(rs.REPO_ROOT / "conversation_history.json") == \
        (tmp_path / "data").resolve() / "install_state" / "conversation_history.json"
    outside = tmp_path / "elsewhere" / "x.json"
    assert rs.install_state_path(outside) == outside, "paths outside the install tree are left alone"


def test_identity_on_a_source_checkout(monkeypatch):
    import runtime_safety as rs

    monkeypatch.setattr(rs, "_INSTALLED", False)
    p = rs.AGENT_DIR / ".governance"
    assert rs.install_state_path(p) == p


def test_not_installed_without_a_data_dir(monkeypatch, tmp_path):
    import runtime_safety as rs

    marker = tmp_path / ".layla_installed"
    marker.write_text("x", encoding="utf-8")
    monkeypatch.setattr(rs, "INSTALL_MARKER", marker)
    monkeypatch.delenv("LAYLA_DATA_DIR", raising=False)
    monkeypatch.setattr(rs, "_INSTALLED", None)
    assert rs.is_installed_build() is False, "with nowhere else to write, keep the historical location"


def test_governance_has_one_owner():
    import main
    import runtime_safety as rs
    from layla.scheduler import jobs

    assert main.GOV_PATH == rs.GOV_PATH
    assert main.PENDING_FILE == rs.GOV_PATH / "pending.json"
    assert jobs._GOV_PATH == rs.GOV_PATH


def test_approval_is_queued_where_pending_reads_it(monkeypatch, tmp_path):
    """The writer (approval_helpers._write_pending) resolves runtime_safety.GOV_PATH at call time; the
    reader (main._read_pending -> GET /pending) reads main.PENDING_FILE == GOV_PATH/pending.json."""
    import main
    import runtime_safety as rs
    from services.agent.approval_helpers import _write_pending

    gov = tmp_path / "install_state" / "agent" / ".governance"
    monkeypatch.setattr(rs, "GOV_PATH", gov)
    monkeypatch.setattr(main, "PENDING_FILE", gov / "pending.json")  # what import-time derivation yields
    aid = _write_pending("restore_file_checkpoint", {"checkpoint_id": "probe"})
    assert (gov / "pending.json").is_file(), "the approval must be queued under the owned GOV_PATH"
    assert any(e.get("id") == aid for e in main._read_pending()), "GET /pending must see the queued approval"


def test_research_sandbox_root_has_one_mapping():
    import agent_loop
    from services.reasoning import research_lab

    assert agent_loop.RESEARCH_LAB_ROOT == research_lab.RESEARCH_LAB_ROOT
