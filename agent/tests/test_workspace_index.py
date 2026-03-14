"""Tests for workspace_index (code intelligence, tree-sitter)."""
import pytest

from services.workspace_index import extract_code_architecture, get_architecture_summary


def test_extract_code_architecture_empty():
    result = extract_code_architecture("")
    assert result["functions"] == []
    assert result["classes"] == []
    assert result["imports"] == []
    assert result["calls"] == []


def test_extract_code_architecture_without_treesitter():
    # Without tree-sitter, returns empty structure
    result = extract_code_architecture("def foo(): pass")
    assert isinstance(result, dict)
    assert "functions" in result
    assert "classes" in result


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
