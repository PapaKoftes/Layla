"""Regression: injected 'learnings' must not hijack unrelated turns.

A stored run-echo ("Objective: Research What is a Python decorator? … Provide: a
concise overview, key concepts, …") was being dumped into every prompt's "Things I
remember" section, so a bare "hello" got answered as the remembered topic, template
and all. Two guards prevent recurrence:
  1. the learning quality gate hard-rejects objective/template/marker content, and
  2. load_learnings only injects learnings relevant to the current goal.
"""
import sys
from pathlib import Path

AGENT_DIR = Path(__file__).resolve().parent.parent
if str(AGENT_DIR) not in sys.path:
    sys.path.insert(0, str(AGENT_DIR))


class TestQualityGateRejectsRunEchoes:
    def test_rejects_stored_objective(self):
        from layla.memory.distill import passes_learning_quality_gate
        ok, _ = passes_learning_quality_gate("Objective: hello. Replied. Snippet: Hi there")
        assert ok is False

    def test_rejects_research_template(self):
        from layla.memory.distill import passes_learning_quality_gate
        ok, _ = passes_learning_quality_gate(
            "Objective: Research decorators. Provide: a concise overview, key concepts, best practices."
        )
        assert ok is False

    def test_rejects_leaked_marker(self):
        from layla.memory.distill import passes_learning_quality_gate
        ok, _ = passes_learning_quality_gate("Ready now. [EARNED_TITLE: Water Wizard]")
        assert ok is False

    def test_keeps_real_fact(self):
        from layla.memory.distill import passes_learning_quality_gate
        ok, _ = passes_learning_quality_gate(
            "Paris is the political, cultural, and economic center of France."
        )
        assert ok is True


class TestLoadLearningsRelevanceGate:
    def test_offtopic_learning_not_injected(self):
        from layla.memory.db import save_learning
        from services.prompts.system_head_builder import load_learnings

        save_learning(content="A Python decorator wraps a function to extend its behavior.", kind="general")
        # A greeting / unrelated goal shares no content token -> nothing injected.
        assert "decorator" not in load_learnings(goal="hello").lower()
        assert load_learnings(goal="what time is it in tokyo").lower().find("decorator") == -1

    def test_ontopic_learning_is_injected(self):
        from layla.memory.db import save_learning
        from services.prompts.system_head_builder import load_learnings

        save_learning(content="A Python decorator wraps a function to extend its behavior.", kind="general")
        # A goal that shares the 'decorator' token still retrieves it.
        assert "decorator" in load_learnings(goal="explain a python decorator").lower()
