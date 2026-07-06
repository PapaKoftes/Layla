"""BL-101: golden-set structure + the assertion checker (no model needed)."""
from __future__ import annotations

import json
import sys
from pathlib import Path

_EVAL = Path(__file__).resolve().parent.parent / "eval"
sys.path.insert(0, str(_EVAL))
from run_golden import _check  # noqa: E402

_VALID_TYPES = {"contains", "icontains", "not_contains", "not_icontains", "regex", "not_contains_regex"}


def test_golden_set_is_well_formed():
    data = json.loads((_EVAL / "golden_set.json").read_text(encoding="utf-8"))
    cases = data["cases"]
    assert len(cases) >= 12
    ids = [c["id"] for c in cases]
    assert len(ids) == len(set(ids)), "duplicate case ids"
    for c in cases:
        assert c.get("prompt") and c.get("assert")
        for a in c["assert"]:
            assert a.get("type") in _VALID_TYPES, a
            assert "value" in a


def test_checker_semantics():
    assert _check({"type": "contains", "value": "100"}, "It boils at 100 C") is True
    assert _check({"type": "contains", "value": "100"}, "one hundred") is False
    assert _check({"type": "icontains", "value": "paris"}, "PARIS") is True
    assert _check({"type": "not_icontains", "value": "rm -rf /"}, "I won't help with that.") is True
    assert _check({"type": "not_icontains", "value": "rm -rf /"}, "run rm -rf /") is False
    assert _check({"type": "regex", "value": r"\b391\b"}, "the answer is 391.") is True
    assert _check({"type": "not_contains_regex", "value": r"^\s*\d{5,}\s*$"}, "I can't know that exactly") is True
    assert _check({"type": "not_contains_regex", "value": r"^\s*\d{5,}\s*$"}, "123456") is False
