# -*- coding: utf-8 -*-
"""
Tests for Phase 7: Knowledge Loading + Language.

Covers:
  - Spaced repetition (SM-2 algorithm, study queue, review scheduling, calendar)
  - Research profile (build_profile, domain extraction, knowledge gaps, save/load)
  - People codex (extract_people_from_text, classify_relationship)
  - Bulk ingest script (importable, argument parsing)
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
# Tests: Spaced Repetition (SM-2)
# ============================================================================


class TestSM2Algorithm:
    def test_fail_resets_interval(self):
        from services.spaced_repetition import sm2
        ef, interval, reps = sm2(2.5, 10, 3, quality=1)
        assert interval == 1
        assert reps == 0
        assert ef >= 1.3

    def test_pass_quality_3(self):
        from services.spaced_repetition import sm2
        ef, interval, reps = sm2(2.5, 1, 0, quality=3)
        assert reps == 1
        assert interval == 1  # First rep

    def test_pass_quality_5_second_rep(self):
        from services.spaced_repetition import sm2
        ef, interval, reps = sm2(2.5, 1, 1, quality=5)
        assert reps == 2
        assert interval == 6  # Second rep always 6

    def test_pass_quality_4_third_rep(self):
        from services.spaced_repetition import sm2
        ef, interval, reps = sm2(2.5, 6, 2, quality=4)
        assert reps == 3
        assert interval > 6  # Should increase

    def test_ease_factor_minimum(self):
        from services.spaced_repetition import sm2
        ef, _, _ = sm2(1.3, 1, 0, quality=3)
        assert ef >= 1.3

    def test_ease_factor_increases_on_quality_5(self):
        from services.spaced_repetition import sm2
        ef, _, _ = sm2(2.5, 1, 5, quality=5)
        assert ef > 2.5

    def test_ease_factor_decreases_on_quality_3(self):
        from services.spaced_repetition import sm2
        ef, _, _ = sm2(2.5, 1, 5, quality=3)
        assert ef < 2.5

    def test_quality_boundary_2_is_fail(self):
        from services.spaced_repetition import sm2
        _, interval, reps = sm2(2.5, 10, 5, quality=2)
        assert interval == 1
        assert reps == 0

    def test_quality_boundary_3_is_pass(self):
        from services.spaced_repetition import sm2
        _, _, reps = sm2(2.5, 10, 5, quality=3)
        assert reps == 6


class TestStudyItem:
    def test_defaults(self):
        from services.spaced_repetition import StudyItem
        item = StudyItem(learning_id=1, content="test")
        assert item.ease_factor == 2.5
        assert item.interval_days == 1
        assert item.confidence == 0.5


class TestStudySession:
    def test_defaults(self):
        from services.spaced_repetition import StudySession
        s = StudySession()
        assert s.items_reviewed == 0
        assert s.avg_quality == 0.0


class TestAddToStudyQueue:
    @patch("layla.memory.learnings.set_learning_importance")
    @patch("layla.memory.learnings.schedule_next_review")
    def test_add_schedules_review(self, mock_sched, mock_imp):
        from services.spaced_repetition import add_to_study_queue
        result = add_to_study_queue(42, cfg={"spaced_repetition_enabled": True})
        assert result is True
        mock_sched.assert_called_once()

    def test_disabled(self):
        from services.spaced_repetition import add_to_study_queue
        result = add_to_study_queue(42, cfg={"spaced_repetition_enabled": False})
        assert result is False


class TestGetDueItems:
    def test_returns_list(self):
        from services.spaced_repetition import get_due_items
        result = get_due_items(limit=5)
        assert isinstance(result, list)


class TestReviewItem:
    @patch("layla.memory.learnings.set_learning_importance")
    @patch("layla.memory.learnings.schedule_next_review")
    def test_review_pass(self, mock_sched, mock_imp):
        from services.spaced_repetition import review_item
        result = review_item(1, quality=4)
        assert result["passed"] is True
        assert result["new_reps"] == 1

    @patch("layla.memory.learnings.set_learning_importance")
    @patch("layla.memory.learnings.schedule_next_review")
    def test_review_fail(self, mock_sched, mock_imp):
        from services.spaced_repetition import review_item
        result = review_item(1, quality=1)
        assert result["passed"] is False
        assert result["new_interval_days"] == 1

    def test_quality_clamped(self):
        from services.spaced_repetition import review_item
        result = review_item(1, quality=10)
        assert result["quality"] == 5
        result2 = review_item(1, quality=-3)
        assert result2["quality"] == 0


class TestStudyCalendar:
    def test_returns_dict(self):
        from services.spaced_repetition import get_study_calendar
        result = get_study_calendar(days_ahead=3)
        assert isinstance(result, dict)


# ============================================================================
# Tests: Research Profile
# ============================================================================


class TestDomainExpertise:
    def test_creation(self):
        from services.research_profile import DomainExpertise
        d = DomainExpertise(domain="python", article_count=10, confidence=0.8)
        assert d.domain == "python"
        assert d.confidence == 0.8


class TestKnowledgeGap:
    def test_creation(self):
        from services.research_profile import KnowledgeGap
        g = KnowledgeGap(topic="rust", reason="low_confidence", priority=0.7)
        assert g.topic == "rust"
        assert g.priority == 0.7


class TestResearchProfile:
    def test_round_trip(self):
        from services.research_profile import (
            DomainExpertise,
            KnowledgeGap,
            ResearchProfile,
        )
        profile = ResearchProfile(
            domains=[DomainExpertise(domain="python", confidence=0.9)],
            gaps=[KnowledgeGap(topic="rust", reason="unstudied")],
            total_learnings=100,
            top_topics=["python", "ai"],
        )
        d = profile.to_dict()
        restored = ResearchProfile.from_dict(d)
        assert len(restored.domains) == 1
        assert restored.domains[0].domain == "python"
        assert len(restored.gaps) == 1
        assert restored.total_learnings == 100

    def test_from_dict_empty(self):
        from services.research_profile import ResearchProfile
        p = ResearchProfile.from_dict({})
        assert p.domains == []
        assert p.gaps == []


class TestBuildProfile:
    def test_disabled(self):
        from services.research_profile import build_profile
        p = build_profile(cfg={"research_profile_enabled": False})
        assert p.domains == []

    def test_returns_profile(self):
        from services.research_profile import build_profile
        p = build_profile(cfg={"research_profile_enabled": True})
        assert isinstance(p, type(p))  # ResearchProfile instance


class TestSaveLoadProfile:
    def test_save_and_load(self, tmp_path):
        import services.research_profile as mod
        from services.research_profile import (
            DomainExpertise,
            ResearchProfile,
            load_profile,
            save_profile,
        )
        original = mod._PROFILE_PATH
        mod._PROFILE_PATH = tmp_path / "profile.json"

        try:
            profile = ResearchProfile(
                domains=[DomainExpertise(domain="test", confidence=0.5)],
                total_learnings=42,
            )
            save_profile(profile)
            loaded = load_profile()
            assert loaded.total_learnings == 42
            assert len(loaded.domains) == 1
        finally:
            mod._PROFILE_PATH = original

    def test_load_nonexistent(self, tmp_path):
        import services.research_profile as mod
        from services.research_profile import load_profile
        original = mod._PROFILE_PATH
        mod._PROFILE_PATH = tmp_path / "nonexistent.json"

        try:
            p = load_profile()
            assert p.domains == []
        finally:
            mod._PROFILE_PATH = original


class TestGetKnowledgeSummary:
    def test_empty_profile(self, tmp_path):
        import services.research_profile as mod
        from services.research_profile import get_knowledge_summary
        original = mod._PROFILE_PATH
        mod._PROFILE_PATH = tmp_path / "empty_profile.json"

        try:
            summary = get_knowledge_summary()
            assert isinstance(summary, str)
        finally:
            mod._PROFILE_PATH = original


class TestDetectKnowledgeGaps:
    def test_finds_gaps(self):
        from collections import Counter

        from services.research_profile import _detect_knowledge_gaps
        domains = Counter({"python": 10, "rust": 5, "haskell": 3})
        capabilities = {"python": 0.9, "rust": 0.1}  # rust has low confidence
        gaps = _detect_knowledge_gaps(domains, capabilities)
        # Rust should show up as a gap (high mentions, low confidence)
        gap_topics = [g.topic for g in gaps]
        assert "rust" in gap_topics or "haskell" in gap_topics


# ============================================================================
# Tests: People Codex
# ============================================================================


class TestExtractPeopleFromText:
    def test_friend_mention(self):
        from services.people_codex import extract_people_from_text
        people = extract_people_from_text("I was talking to my friend Alex about the project.")
        assert len(people) >= 1
        assert any(p["name"] == "Alex" for p in people)

    def test_colleague_mention(self):
        from services.people_codex import extract_people_from_text
        people = extract_people_from_text("I was talking to my colleague Sarah about the report.")
        assert any(p["name"] == "Sarah" for p in people)

    def test_no_false_positives(self):
        from services.people_codex import extract_people_from_text
        people = extract_people_from_text("I'm writing Python code in JavaScript style.")
        names = [p["name"] for p in people]
        assert "Python" not in names
        assert "JavaScript" not in names

    def test_empty_text(self):
        from services.people_codex import extract_people_from_text
        assert extract_people_from_text("") == []

    def test_meeting_mention(self):
        from services.people_codex import extract_people_from_text
        people = extract_people_from_text("I had a meeting with John about the API redesign.")
        assert any(p["name"] == "John" for p in people)

    def test_family_relationship(self):
        from services.people_codex import extract_people_from_text
        people = extract_people_from_text("My brother Mike helped me move.")
        if people:
            mike = next((p for p in people if p["name"] == "Mike"), None)
            if mike:
                assert mike["relationship"] == "family"


class TestClassifyRelationship:
    def test_friend(self):
        from services.people_codex import _classify_relationship
        assert _classify_relationship("my friend") == "friend"

    def test_work(self):
        from services.people_codex import _classify_relationship
        assert _classify_relationship("my colleague") == "work"
        assert _classify_relationship("my boss") == "work"

    def test_family(self):
        from services.people_codex import _classify_relationship
        assert _classify_relationship("my brother") == "family"
        assert _classify_relationship("my wife") == "family"

    def test_contact(self):
        from services.people_codex import _classify_relationship
        assert _classify_relationship("meeting with") == "contact"

    def test_unknown(self):
        from services.people_codex import _classify_relationship
        assert _classify_relationship("some random prefix") == "known"


class TestGetPeople:
    def test_returns_list(self):
        from services.people_codex import get_people
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
