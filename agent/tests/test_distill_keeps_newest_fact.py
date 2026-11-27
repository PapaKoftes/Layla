"""Merging similar memories keeps the NEWEST statement of a fact first, and labels the old value.

Live (jinx-20b): after "The operator's favorite color code is teal-ebab." was learned, distillation merged it
with the earlier "... teal-d2c3." into "...teal-d2c3. ...teal-ebab. [merged from 2 similar]" (oldest first),
and "What is my favorite color code?" was answered "teal-d2c3".
"""
import sys
from pathlib import Path

AGENT_DIR = Path(__file__).resolve().parent.parent
if str(AGENT_DIR) not in sys.path:
    sys.path.insert(0, str(AGENT_DIR))

OLD = {"id": 7, "content": "The operator's favorite color code is teal-d2c3.", "created_at": "2026-11-22T16:30:00+00:00"}
NEW = {"id": 9, "content": "The operator's favorite color code is teal-ebab.", "created_at": "2026-11-27T01:20:00+00:00"}


def test_probe_the_two_facts_really_get_merged():
    from layla.memory.distill import _group_similar

    groups = _group_similar([OLD, NEW])
    assert len(groups) == 1 and len(groups[0]) == 2, "PROBE BROKEN: these facts are no longer grouped"


def test_newest_value_leads_and_the_old_value_is_dropped_whatever_the_input_order():
    """Kept as "Earlier: ..." the old value was still picked by the model live, so it is dropped."""
    from layla.memory.distill import _summarize_group

    for group in ([OLD, NEW], [NEW, OLD]):
        s = _summarize_group(group)
        assert s.startswith("The operator's favorite color code is teal-ebab."), s
        assert "teal-d2c3" not in s, s


def test_newest_value_survives_a_later_merge():
    from layla.memory.distill import _summarize_group

    first = {"id": 10, "content": _summarize_group([OLD, NEW]), "created_at": "2026-11-27T01:22:00+00:00"}
    older_merge = {"id": 3, "content": "The operator's favorite color code is teal-b6c9. The operator's favorite "
                                       "color code is teal-79bc. [merged from 2 similar]",
                   "created_at": "2026-11-20T00:00:00+00:00"}
    s = _summarize_group([older_merge, first])
    assert s.startswith("The operator's favorite color code is teal-ebab."), s


def test_distinct_similar_facts_are_both_kept():
    from layla.memory.distill import _summarize_group

    a = {"id": 1, "content": "Fixed bug in login. User can now sign in.", "created_at": "2026-01-01"}
    b = {"id": 2, "content": "Fixed bug in login flow for admins today.", "created_at": "2026-01-02"}
    s = _summarize_group([a, b])
    assert "Fixed bug in login." in s and "admins today" in s, s
