from services.context_merge_layers import MEMORY_SECTION_ORDER, merge_memory_sections


def test_merge_memory_sections_order():
    d = {
        "reasoning_strategies": "z_last",
        "learnings": "b",
        "git_preamble": "a",
    }
    out = merge_memory_sections(d)
    assert out.index("a") < out.index("b")
    assert out.index("b") < out.index("z_last")


def test_memory_order_keys_complete():
    assert "git_preamble" in MEMORY_SECTION_ORDER
    assert MEMORY_SECTION_ORDER.index("learnings") < MEMORY_SECTION_ORDER.index("semantic_recall")
