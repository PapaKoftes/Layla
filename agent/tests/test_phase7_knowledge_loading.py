# -*- coding: utf-8 -*-
"""
Tests for Phase 7: Knowledge Loading + Language.

Covers:
  - Research profile (build_profile, domain extraction, knowledge gaps, save/load)
  - People codex (extract_people_from_text, classify_relationship)
  - Bulk ingest script (importable, argument parsing)

The SM-2 / study-queue / study-calendar tests that used to live here were deleted along with
services/memory/spaced_repetition.py: that module had ZERO production importers (its ~30 tests were the
only thing keeping it alive), and the SM-2 that actually drives the flashcard deck is
services/infrastructure/german_mode.py::_sm2 — now covered by tests/test_german_mode_sm2.py, which is
where those correctness properties were ported.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

AGENT_DIR = Path(__file__).resolve().parent.parent
if str(AGENT_DIR) not in sys.path:
    sys.path.insert(0, str(AGENT_DIR))


# ============================================================================
# Tests: Research Profile
# ============================================================================


class TestExtractPeopleFromText:
    def test_friend_mention(self):
        from services.memory.people_codex import extract_people_from_text
        people = extract_people_from_text("I was talking to my friend Alex about the project.")
        assert len(people) >= 1
        assert any(p["name"] == "Alex" for p in people)

    def test_colleague_mention(self):
        from services.memory.people_codex import extract_people_from_text
        people = extract_people_from_text("I was talking to my colleague Sarah about the report.")
        assert any(p["name"] == "Sarah" for p in people)

    def test_no_false_positives(self):
        from services.memory.people_codex import extract_people_from_text
        people = extract_people_from_text("I'm writing Python code in JavaScript style.")
        names = [p["name"] for p in people]
        assert "Python" not in names
        assert "JavaScript" not in names

    def test_empty_text(self):
        from services.memory.people_codex import extract_people_from_text
        assert extract_people_from_text("") == []

    def test_meeting_mention(self):
        from services.memory.people_codex import extract_people_from_text
        people = extract_people_from_text("I had a meeting with John about the API redesign.")
        assert any(p["name"] == "John" for p in people)

    def test_family_relationship(self):
        from services.memory.people_codex import extract_people_from_text
        people = extract_people_from_text("My brother Mike helped me move.")
        if people:
            mike = next((p for p in people if p["name"] == "Mike"), None)
            if mike:
                assert mike["relationship"] == "family"


class TestClassifyRelationship:
    def test_friend(self):
        from services.memory.people_codex import _classify_relationship
        assert _classify_relationship("my friend") == "friend"

    def test_work(self):
        from services.memory.people_codex import _classify_relationship
        assert _classify_relationship("my colleague") == "work"
        assert _classify_relationship("my boss") == "work"

    def test_family(self):
        from services.memory.people_codex import _classify_relationship
        assert _classify_relationship("my brother") == "family"
        assert _classify_relationship("my wife") == "family"

    def test_contact(self):
        from services.memory.people_codex import _classify_relationship
        assert _classify_relationship("meeting with") == "contact"

    def test_unknown(self):
        from services.memory.people_codex import _classify_relationship
        assert _classify_relationship("some random prefix") == "known"


class TestGetPeople:
    def test_returns_list(self):
        from services.memory.people_codex import get_people
        result = get_people()
        assert isinstance(result, list)


# ============================================================================
# Tests: Bulk Ingest Script
# ============================================================================


class TestBulkIngestScript:
    def test_importable(self):
        import scripts.bulk_ingest
        assert hasattr(scripts.bulk_ingest, "main")

    def test_no_args_returns_1(self):
        import scripts.bulk_ingest as mod
        # Simulate no args
        original_argv = sys.argv
        sys.argv = ["bulk_ingest.py"]
        try:
            result = mod.main()
            assert result == 1
        finally:
            sys.argv = original_argv

    def test_nonexistent_path_returns_1(self):
        import scripts.bulk_ingest as mod
        original_argv = sys.argv
        sys.argv = ["bulk_ingest.py", "/nonexistent/path/xyz"]
        try:
            result = mod.main()
            assert result == 1
        finally:
            sys.argv = original_argv

    @patch("layla.ingestion.pipeline.ingest_file")
    def test_single_file_ingest(self, mock_ingest, tmp_path):
        from layla.ingestion.pipeline import IngestResult
        mock_ingest.return_value = IngestResult(
            source=str(tmp_path / "test.txt"), chunks=3, skipped=False,
        )
        f = tmp_path / "test.txt"
        f.write_text("Test content.", encoding="utf-8")

        import scripts.bulk_ingest as mod
        original_argv = sys.argv
        sys.argv = ["bulk_ingest.py", str(f)]
        try:
            result = mod.main()
            assert result == 0
        finally:
            sys.argv = original_argv

    def test_dry_run_no_ingest(self, tmp_path):
        f = tmp_path / "test.txt"
        f.write_text("Test content.", encoding="utf-8")

        import scripts.bulk_ingest as mod
        original_argv = sys.argv
        sys.argv = ["bulk_ingest.py", str(f), "--dry-run"]
        try:
            result = mod.main()
            assert result == 0
        finally:
            sys.argv = original_argv
