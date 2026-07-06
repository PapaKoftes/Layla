"""Feature: finished research reports are ingested into the searchable KB (recallable
memory), not just written to .research_brain/ files."""
from __future__ import annotations

from unittest.mock import patch

from services.infrastructure import research_report as rr

_LONG = "# Research report\n\n" + ("A cited, sectioned finding about the topic. " * 20)


def test_report_ingested_into_kb_when_long():
    with patch("services.workspace.kb_builder.build_kb_from_texts", return_value={"ok": True, "articles": 1}) as m:
        out = rr.save_report_to_kb(_LONG, title="Research: X")
        assert out == {"ok": True, "articles": 1}
        m.assert_called_once()
        args, kwargs = m.call_args
        assert args[0] == [_LONG]                 # the report text is what gets ingested
        assert kwargs.get("topic") == "Research: X"


def test_short_report_is_skipped():
    with patch("services.workspace.kb_builder.build_kb_from_texts") as m:
        assert rr.save_report_to_kb("too short", title="X") is None
        m.assert_not_called()


def test_disabled_via_config():
    with patch("runtime_safety.load_config", return_value={"research_kb_ingest_enabled": False}), \
         patch("services.workspace.kb_builder.build_kb_from_texts") as m:
        assert rr.save_report_to_kb(_LONG, title="X") is None
        m.assert_not_called()


def test_kb_failure_is_swallowed():
    with patch("services.workspace.kb_builder.build_kb_from_texts", side_effect=RuntimeError("boom")):
        assert rr.save_report_to_kb(_LONG, title="X") is None   # best-effort, never raises
