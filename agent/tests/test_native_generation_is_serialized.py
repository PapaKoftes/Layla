"""Every native generation on the shared Llama holds THE inference lock.

The GBNF agent decision and the post-turn memory-fact extraction called llm.create_completion directly,
outside the lock run_completion holds. llama-cpp drops the GIL during generation, so a background
extraction for the previous turn could run on the same instance as the next turn's decision. Live: a
forced write_file decision came back unusable and the turn replied "banana" without writing (1 in 3
suite rounds), right after the previous turn's post-turn work started.
"""
import ast
import sys
from pathlib import Path

import pytest

AGENT_DIR = Path(__file__).resolve().parent.parent
if str(AGENT_DIR) not in sys.path:
    sys.path.insert(0, str(AGENT_DIR))


class _LockCheckingLlm:
    def __init__(self, text):
        self.text, self.held = text, []

    def create_completion(self, *a, **k):
        from services.llm.llm_gateway import inference_lock

        self.held.append(inference_lock()._is_owned())
        return {"choices": [{"text": self.text}]}


@pytest.fixture(autouse=True)
def _plain_prompt(monkeypatch):
    import services.llm.prompt_format as pf

    monkeypatch.setattr(pf, "format_raw_prompt", lambda llm, prompt: prompt)


def test_gbnf_agent_decision_holds_the_inference_lock():
    pytest.importorskip("llama_cpp")
    from services.llm.gbnf_grammar import run_gbnf_agent_decision

    llm = _LockCheckingLlm('{"action":"tool","tool":"write_file","args":{"path":"a.txt","content":"banana"}}')
    out = run_gbnf_agent_decision(llm, "p", max_tokens=64, temperature=0.0,
                                  valid_tools=frozenset({"write_file", "reason"}), force_tool="write_file")
    assert llm.held, "PROBE BROKEN: the fake model was never called"
    assert llm.held == [True], llm.held
    assert out and out.get("tool") == "write_file", out


def test_gbnf_memory_extraction_holds_the_inference_lock():
    pytest.importorskip("llama_cpp")
    from services.llm.gbnf_grammar import run_gbnf_memory_extraction

    llm = _LockCheckingLlm('{"subject":"none","type":"episodic","fact":"","confidence":0.0}')
    run_gbnf_memory_extraction(llm, "p")
    assert llm.held == [True], llm.held


def test_inference_lock_follows_the_per_workspace_setting():
    from services.llm import llm_gateway as gw

    assert gw.inference_lock({}) is gw.llm_serialize_lock
    assert gw.inference_lock({"llm_serialize_per_workspace": True}) is gw.llm_generation_lock


def test_direct_create_completion_call_sites_are_all_reviewed():
    """A NEW direct create_completion call must be added here deliberately, after checking it holds the lock."""
    reviewed = {
        "services/llm/gbnf_grammar.py": 2,       # both under `with inference_lock()`
        "services/llm/model_benchmark.py": 1,    # under `with inference_lock(cfg)`
        "services/llm/inference_router.py": 1,   # _call_create_completion, only invoked under _llm_lock
    }
    found: dict[str, int] = {}
    for py in (AGENT_DIR / "services").rglob("*.py"):
        tree = ast.parse(py.read_text(encoding="utf-8"))
        n = sum(1 for c in ast.walk(tree) if isinstance(c, ast.Call)
                and isinstance(c.func, ast.Attribute) and c.func.attr == "create_completion")
        if n:
            found[py.relative_to(AGENT_DIR).as_posix()] = n
    assert found, "PROBE BROKEN: no create_completion call sites found at all"
    assert found == reviewed, found
