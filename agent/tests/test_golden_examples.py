from __future__ import annotations


def test_golden_examples_store_and_retrieve():
    from services.golden_examples import (
        format_for_prompt,
        retrieve_relevant_examples,
        store_golden_example,
    )

    ok = store_golden_example(
        task_type="agent",
        goal="Fix bug in agent_loop decision parsing for JSON output",
        decision_pattern='{"action":"tool","tool":"read_file"}',
        score=0.95,
    )
    assert ok is True

    ex = retrieve_relevant_examples(
        "Please fix decision parsing for JSON output in agent_loop",
        "agent",
        k=2,
    )
    assert ex
    txt = format_for_prompt(ex, max_chars=800)
    assert "Successful patterns" in txt

