"""Models address the workspace root as "/", ".", "" — those must mean the sandbox root, never the drive root.
Live on jinx-20b: list_dir {"path": "/"} -> "Path not found" -> the reply said "the workspace is empty"."""
import sys
from pathlib import Path

import pytest

AGENT_DIR = Path(__file__).resolve().parent.parent
if str(AGENT_DIR) not in sys.path:
    sys.path.insert(0, str(AGENT_DIR))


@pytest.fixture
def ws(tmp_path, monkeypatch):
    from layla.tools.impl import file_ops

    (tmp_path / "a.md").write_text("x", encoding="utf-8")
    monkeypatch.setattr(file_ops, "_get_sandbox", lambda: tmp_path)
    monkeypatch.setattr(file_ops._effective_sandbox, "path", None, raising=False)
    monkeypatch.setattr(file_ops, "inside_sandbox", lambda p: str(Path(p).resolve()).startswith(str(tmp_path.resolve())))
    return tmp_path, file_ops


@pytest.mark.parametrize("alias", ["/", "\\", ".", "./", "", " / "])
def test_root_aliases_list_the_workspace(ws, alias):
    root, fo = ws
    r = fo.list_dir(alias)
    assert r.get("ok") and [e["name"] for e in r["entries"]] == ["a.md"], r


@pytest.mark.skipif(sys.platform != "win32", reason="drive-less rooted paths exist only on Windows; "
                    "on POSIX /a.md is truly absolute and stays subject to the sandbox check")
def test_rooted_driveless_path_is_workspace_relative(ws):
    root, fo = ws
    assert fo._resolve_sandboxed_path("/a.md") == (root / "a.md").resolve()


def test_real_absolute_paths_still_go_through_the_sandbox_check(ws, tmp_path_factory):
    root, fo = ws
    outside = tmp_path_factory.mktemp("elsewhere")
    assert fo.list_dir(str(outside)).get("ok") is False


def test_workspace_word_and_root_name_mean_the_root(ws):
    """Live: list_dir {"path": "/workspace"} -> "Path not found" -> "your workspace path is invalid"."""
    root, fo = ws
    for alias in ("/workspace", "workspace", "./workspace/", r"\workspace", "/" + root.name):
        assert fo._resolve_sandboxed_path(alias) == root.resolve(), alias


def test_a_real_subfolder_named_workspace_still_wins(ws):
    root, fo = ws
    (root / "workspace").mkdir()
    assert fo._resolve_sandboxed_path("workspace") == (root / "workspace").resolve()
