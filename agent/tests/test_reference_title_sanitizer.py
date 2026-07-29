"""_strip_bare_reference_titles: drop a reference-doc's redundant leading '# Title' when it sits
directly above another heading.

Curated knowledge docs open with '# Title' then '## Section'; injected under a '--- <file> ---'
banner that already names the doc, that title is a *bare* header the model imitates. This is the
interior case `_drop_dangling_headers` (tail-only) misses, and the class behind the
test_no_dangling_headers failure (11 shipped docs share the shape). These tests pin the exact
surgical behaviour: level-1 bare titles go, real structure stays.
"""
from __future__ import annotations

from services.prompts.system_head_builder import _strip_bare_reference_titles as strip


def test_drops_bare_leading_title_above_subheading():
    blob = "--- api-design-patterns.md ---\n# API design patterns\n\n## REST semantics\n\n- GET is safe."
    out = strip(blob)
    assert "# API design patterns" not in out
    assert "## REST semantics" in out          # the real section survives
    assert "- GET is safe." in out             # body survives
    assert "--- api-design-patterns.md ---" in out  # banner survives (identifies the doc)


def test_keeps_title_that_has_body_directly_beneath():
    blob = "# Real Title\n\nThis is an intro paragraph with actual content.\n\n## Section\n- x"
    out = strip(blob)
    assert "# Real Title" in out               # NOT bare — has body under it


def test_does_not_touch_interior_subheadings():
    # A '## A' directly above '### B' is the doc's own structure, not a redundant banner-title.
    blob = "--- d.md ---\n## A\n### B\n- body"
    out = strip(blob)
    assert "## A" in out and "### B" in out


def test_multiple_chunks_each_lose_only_the_bare_title():
    blob = (
        "--- a.md ---\n# Alpha\n\n## S1\n- one\n\n"
        "--- b.md ---\n# Beta\n\n## S2\n- two"
    )
    out = strip(blob)
    assert "# Alpha" not in out and "# Beta" not in out
    assert "## S1" in out and "## S2" in out
    assert "- one" in out and "- two" in out


def test_no_bare_headers_remain_by_the_test_module_rule():
    """Mirror test_no_dangling_headers' own predicate: no heading may be immediately followed by
    another heading (or be trailing) after sanitising."""
    blob = "--- x.md ---\n# Title\n\n## Section\n\nbody line"
    out = strip(blob)
    lines = out.split("\n")
    bare = []
    for i, ln in enumerate(lines):
        s = ln.strip()
        if not s.startswith("#"):
            continue
        nxt = next((lines[j].strip() for j in range(i + 1, len(lines)) if lines[j].strip()), None)
        if nxt is None or nxt.startswith("#"):
            bare.append(s)
    assert bare == []


def test_empty_and_headingless_are_noops():
    assert strip("") == ""
    assert strip("just some prose\nwith no headings") == "just some prose\nwith no headings"
