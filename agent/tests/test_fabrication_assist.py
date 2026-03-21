"""Smoke tests for root-level fabrication_assist (repo root on sys.path)."""

from __future__ import annotations

import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from fabrication_assist.assist.explain import format_comparison_table, summarize_best
from fabrication_assist.assist.layla_lite import assist, parse_intent
from fabrication_assist.assist.runner import StubRunner
from fabrication_assist.assist.session import AssistSession, load_session, save_session


def test_session_roundtrip(tmp_path: Path) -> None:
    p = tmp_path / "sess.json"
    s = AssistSession()
    s.append_history({"t": 1})
    s.preferences["units"] = "mm"
    save_session(s, p)
    s2 = load_session(p)
    assert s2.history == [{"t": 1}]
    assert s2.preferences.get("units") == "mm"


def test_stub_assist_end_to_end(tmp_path: Path) -> None:
    p = tmp_path / "assist.json"
    out = assist(
        "CNC bracket minimize machining time",
        session_path=p,
        runner=StubRunner(),
    )
    assert len(out["variants"]) == 3
    assert len(out["results"]) == 3
    md = out["markdown"]
    assert md
    assert "Assist summary" in md
    assert "|" in md  # table
    s3 = load_session(p)
    assert len(s3.history) == 1
    assert len(s3.outcomes) == 3


def test_explain_non_empty() -> None:
    r = StubRunner().run_build({"id": "a", "label": "A"})
    r2 = StubRunner().run_build({"id": "b", "label": "B"})
    tab = format_comparison_table([r, r2])
    assert tab.strip()
    summ = summarize_best([r, r2])
    assert summ


def test_parse_intent_keywords() -> None:
    i = parse_intent("easy assembly snap fit enclosure")
    assert "assembly_simplicity" in i["strategies"]
    assert i.get("goal") == "enclosure"


def test_summarize_best_all_zero_scores() -> None:
    rows = [
        {"variant_id": "a", "label": "A", "score": 0.0, "metrics": {}, "feasible": True, "notes": ""},
        {"variant_id": "b", "label": "B", "score": 0.0, "metrics": {}, "feasible": True, "notes": ""},
    ]
    s = summarize_best(rows)
    assert "A" in s or "B" in s
    assert "0.0" in s or "0" in s


def test_summarize_best_missing_score_treated_as_zero() -> None:
    rows = [{"variant_id": "z", "label": "Z", "metrics": {}, "feasible": True, "notes": "n"}]
    s = summarize_best(rows)
    assert "Z" in s
