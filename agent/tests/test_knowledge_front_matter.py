from __future__ import annotations


def test_parse_knowledge_front_matter_extended_fields():
    from layla.memory.vector_store import _parse_knowledge_front_matter

    text = """---
priority: core
domain: devops
aspects: Morrigan, Nyx
difficulty: intermediate
related: foo.md, bar/baz.md
---

# Title
Body
"""
    fm = _parse_knowledge_front_matter(text)
    assert isinstance(fm, dict)
    assert fm.get("priority") == "core"
    assert fm.get("domain") == "devops"
    assert fm.get("difficulty") == "intermediate"
    assert fm.get("aspects") == ["morrigan", "nyx"]
    assert fm.get("related") == ["foo.md", "bar/baz.md"]

