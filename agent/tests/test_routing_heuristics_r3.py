"""audit round-3: #6 classify_task must not tag prose ("write me a haiku") as coding;
#7 should_deliberate must word-boundary match (no "decided"->"decide") and require a real
decision signal alongside length, not length alone."""
import sys
from pathlib import Path

AGENT_DIR = Path(__file__).resolve().parent.parent
if str(AGENT_DIR) not in sys.path:
    sys.path.insert(0, str(AGENT_DIR))


def test_classify_task_prose_write_is_not_coding():
    from services.llm.model_router import classify_task as C
    # Ambiguous prose verbs alone are NOT coding.
    assert C("write me a haiku about spring") != "coding"
    assert C("write a cover letter") != "coding"
    # But real coding intent still routes to coding.
    assert C("refactor the auth module") == "coding"
    assert C("write a python function to sort a list") == "coding"
    assert C("fix the bug in def parse():") == "coding"


def test_should_deliberate_word_boundaries_and_length(monkeypatch):
    import orchestrator as O
    import runtime_safety
    monkeypatch.setattr(runtime_safety, "load_config", lambda: {"deliberation_enabled": True})
    # "decided" must NOT trip the "decide" phrase; a long plain statement isn't a deliberation request.
    assert O.should_deliberate(
        "I decided to refactor the auth module today because the old code was messy and needed cleanup.",
        {},
    ) is False
    assert O.should_deliberate("this is a discussion of history", {}) is False
    # Genuine decision questions still deliberate.
    assert O.should_deliberate("what should i do about caching?", {}) is True
    assert O.should_deliberate("should i use redis or memcached?", {}) is True
