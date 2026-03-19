"""code_intelligence facade over workspace_index."""

import pytest

pytest.importorskip("tree_sitter")
pytest.importorskip("tree_sitter_python")


def test_search_symbols_finds_function(tmp_path):
    p = tmp_path / "mod.py"
    p.write_text(
        "def hello_world():\n    return 1\n\nclass Foo:\n    pass\n",
        encoding="utf-8",
    )
    from services.code_intelligence import search_symbols

    out = search_symbols(tmp_path, "hello_world", k=10)
    assert out.get("ok") is True
    matches = out.get("matches") or []
    assert any(m.get("name") == "hello_world" for m in matches)


def test_search_symbols_empty_symbol(tmp_path):
    from services.code_intelligence import search_symbols

    out = search_symbols(tmp_path, "", k=5)
    assert out.get("ok") is False
