"""Tests for workspace_index (code intelligence, tree-sitter).

BL-302 NOTE. `test_extract_code_architecture_without_treesitter` used to read:

    result = extract_code_architecture("def foo(): pass")
    assert isinstance(result, dict)
    assert "functions" in result
    assert "classes" in result

It passed on ALL-EMPTY output, so it could not fail. It passed with tree-sitter installed and without it;
it passed whether extraction worked or was completely broken; and it would have passed if the function
returned `{"functions": [], "classes": [], "imports": [], "calls": []}` forever — which, on this machine,
is exactly what it does. The test did not merely miss the breakage, it CODIFIED it: "Without tree-sitter,
returns empty structure" was written as the expectation.

That mattered, because all-empty here is the same false negative that made `search_codebase` claim real
symbols did not exist (BL-302): the caller cannot distinguish "no functions in this source" from "no
parser installed". The fix below ties the assertion to the CAUSE — `_get_parser()` — so emptiness is only
acceptable when the parser is genuinely absent.
"""
import pytest

from services.workspace.workspace_index import (
    _get_parser,
    extract_code_architecture,
    get_architecture_summary,
)


def test_extract_code_architecture_empty():
    result = extract_code_architecture("")
    assert result["functions"] == []
    assert result["classes"] == []
    assert result["imports"] == []
    assert result["calls"] == []


def test_extract_code_architecture_emptiness_is_explained_by_a_missing_parser():
    """Emptiness must be attributable to the missing parser — never silent.

    Both branches can fail, which is the property the old test lacked:
      - parser present, `foo` not found  -> extraction is broken (previously invisible)
      - parser absent, `foo` found       -> someone added a fallback; update this test and the manifest

    tree-sitter is commented out of requirements.txt:127 and is in neither venv, so the second branch is
    the one that runs here. `services.workspace.repo_indexer` is the ast-based path that does NOT need
    tree-sitter and is what `search_codebase` uses.
    """
    result = extract_code_architecture("def foo(): pass")
    assert isinstance(result, dict)
    assert {"functions", "classes", "imports", "calls"} <= set(result)

    if _get_parser() is not None:
        assert [f["name"] for f in result["functions"]] == ["foo"], (
            "tree-sitter IS installed but extraction found no functions — extraction is broken. The old "
            "version of this test passed in exactly this state."
        )
    else:
        assert result["functions"] == [], (
            "extract_code_architecture found symbols with NO tree-sitter parser available — an ast "
            "fallback was added. That is good news: update this test to assert the real behaviour, and "
            "drop the tree-sitter caveat from .identity/capabilities.md."
        )


def test_extract_code_architecture_with_treesitter():
    try:
        from tree_sitter import Parser
        from tree_sitter_python import language
        Parser(language())
    except ImportError:
        pytest.skip("tree-sitter-python not installed")
    code = '''
def greet():
    print("hello")

class Foo:
    def bar(self):
        return 1
'''
    result = extract_code_architecture(code)
    assert "functions" in result
    assert "classes" in result
    # With tree-sitter we should find at least one function or class
    assert len(result["functions"]) >= 1 or len(result["classes"]) >= 1


def test_get_architecture_summary_invalid_path():
    assert get_architecture_summary("/nonexistent/path") == ""
