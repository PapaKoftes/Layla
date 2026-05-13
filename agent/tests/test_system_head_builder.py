"""Tests for system_head_builder module (extracted from agent_loop.py)."""
import pytest


class TestIsLightweightChatTurn:
    def test_phatic_greeting(self):
        from services.system_head_builder import is_lightweight_chat_turn
        assert is_lightweight_chat_turn("hi", "light") is True

    def test_phatic_thanks(self):
        from services.system_head_builder import is_lightweight_chat_turn
        assert is_lightweight_chat_turn("thanks", "light") is True

    def test_phatic_ok(self):
        from services.system_head_builder import is_lightweight_chat_turn
        assert is_lightweight_chat_turn("ok", "light") is True

    def test_question_is_substantive(self):
        from services.system_head_builder import is_lightweight_chat_turn
        assert is_lightweight_chat_turn("what is Python?", "light") is False

    def test_code_marker_is_substantive(self):
        from services.system_head_builder import is_lightweight_chat_turn
        assert is_lightweight_chat_turn("def foo():", "light") is False

    def test_deep_reasoning_never_lightweight(self):
        from services.system_head_builder import is_lightweight_chat_turn
        assert is_lightweight_chat_turn("hi", "deep") is False

    def test_empty_goal(self):
        from services.system_head_builder import is_lightweight_chat_turn
        assert is_lightweight_chat_turn("", "light") is False


class TestNeedsKnowledgeRag:
    def test_research_keyword(self):
        from services.system_head_builder import needs_knowledge_rag
        assert needs_knowledge_rag("research Python async patterns") is True

    def test_explain_keyword(self):
        from services.system_head_builder import needs_knowledge_rag
        assert needs_knowledge_rag("explain how decorators work") is True

    def test_reflective_keyword(self):
        from services.system_head_builder import needs_knowledge_rag
        assert needs_knowledge_rag("help me reflect on my burnout") is True

    def test_simple_goal(self):
        from services.system_head_builder import needs_knowledge_rag
        assert needs_knowledge_rag("fix the bug in main.py") is False

    def test_empty(self):
        from services.system_head_builder import needs_knowledge_rag
        assert needs_knowledge_rag("") is False


class TestNeedsGraph:
    def test_related_keyword(self):
        from services.system_head_builder import needs_graph
        assert needs_graph("show me related topics") is True

    def test_no_keyword(self):
        from services.system_head_builder import needs_graph
        assert needs_graph("write a test") is False

    def test_empty(self):
        from services.system_head_builder import needs_graph
        assert needs_graph("") is False


class TestExtractAspectDomainKeywords:
    def test_with_domains(self):
        from services.system_head_builder import extract_aspect_domain_keywords
        aspect = {
            "expertise_domains": {
                "primary": ["Python (stdlib, async)", "debugging (pdb)"],
                "secondary": ["testing (pytest)"],
            }
        }
        kw = extract_aspect_domain_keywords(aspect)
        assert "python" in kw
        assert "debugging" in kw
        assert "testing" in kw

    def test_no_aspect(self):
        from services.system_head_builder import extract_aspect_domain_keywords
        assert extract_aspect_domain_keywords(None) == []

    def test_no_domains(self):
        from services.system_head_builder import extract_aspect_domain_keywords
        assert extract_aspect_domain_keywords({"name": "test"}) == []

    def test_capped_at_12(self):
        from services.system_head_builder import extract_aspect_domain_keywords
        aspect = {
            "expertise_domains": {
                "primary": [f"domain{i}" for i in range(20)],
                "secondary": [],
            }
        }
        kw = extract_aspect_domain_keywords(aspect)
        assert len(kw) <= 12


class TestBuildExpertiseDomainBlock:
    def test_with_full_domain(self):
        from services.system_head_builder import build_expertise_domain_block
        aspect = {
            "name": "Echo",
            "expertise_domains": {
                "primary": ["Python", "async"],
                "secondary": ["testing"],
                "philosophy": "Pragmatic engineering",
                "knowledge_gaps_honest": ["Rust", "C++"],
                "can_refuse_technical": ["medical advice"],
            }
        }
        block = build_expertise_domain_block(aspect)
        assert "Domain expertise (Echo):" in block
        assert "Python" in block
        assert "Pragmatic engineering" in block

    def test_no_aspect(self):
        from services.system_head_builder import build_expertise_domain_block
        assert build_expertise_domain_block(None) == ""


class TestGetRepoStructure:
    def test_empty_workspace(self):
        from services.system_head_builder import get_repo_structure
        assert get_repo_structure("") == ""

    def test_nonexistent_dir(self):
        from services.system_head_builder import get_repo_structure
        assert get_repo_structure("/nonexistent/path/xyz") == ""

    def test_valid_dir(self, tmp_path):
        from services.system_head_builder import get_repo_structure
        (tmp_path / "file1.py").write_text("x")
        (tmp_path / "dir1").mkdir()
        result = get_repo_structure(str(tmp_path))
        assert "file1.py" in result
        assert "dir1/" in result


class TestDecomposeGoal:
    def test_short_goal_returns_empty(self):
        from services.system_head_builder import decompose_goal
        assert decompose_goal("fix bug") == []

    def test_empty_goal(self):
        from services.system_head_builder import decompose_goal
        assert decompose_goal("") == []


class TestAppendPersonaFocus:
    def test_no_focus_returns_original(self):
        from services.system_head_builder import append_persona_focus_to_personality
        result = append_persona_focus_to_personality("original", {"id": "echo"}, "")
        assert result == "original"

    def test_same_id_returns_original(self):
        from services.system_head_builder import append_persona_focus_to_personality
        result = append_persona_focus_to_personality("original", {"id": "echo"}, "echo")
        assert result == "original"


class TestRelationshipCodexContext:
    def test_disabled(self):
        from services.system_head_builder import relationship_codex_context
        block, found = relationship_codex_context({}, "")
        assert block == ""
        assert found is False

    def test_no_workspace(self):
        from services.system_head_builder import relationship_codex_context
        block, found = relationship_codex_context({"relationship_codex_inject_enabled": True}, "")
        assert block == ""
        assert found is False


class TestEnrichDeliberationContext:
    def test_empty_context(self):
        from services.system_head_builder import enrich_deliberation_context
        result = enrich_deliberation_context("")
        assert isinstance(result, str)

    def test_passes_through_context(self):
        from services.system_head_builder import enrich_deliberation_context
        result = enrich_deliberation_context("existing context")
        assert "existing context" in result
