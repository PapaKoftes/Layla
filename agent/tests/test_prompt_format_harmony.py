"""gpt-oss (harmony) models need their own turn format; everything else is untouched.

Live on jinx-20b (gpt-oss) the agent never ran a tool: raw text prompts put the model mid-analysis-channel,
so the decision step answered "I have enough context" and the reply printed ``read_file("x")`` as text.
See services/llm/prompt_format.py for the measurement.
"""
import ast
import sys
from pathlib import Path

AGENT_DIR = Path(__file__).resolve().parent.parent
if str(AGENT_DIR) not in sys.path:
    sys.path.insert(0, str(AGENT_DIR))

from services.llm.prompt_format import format_raw_prompt, uses_harmony  # noqa: E402


class _LLM:
    def __init__(self, md):
        self.metadata = md


GPT_OSS = _LLM({"general.architecture": "gpt-oss"})
HARMONY_TEMPLATE = _LLM({"general.architecture": "llama", "tokenizer.chat_template": "...<|channel|>final..."})
CHATML = _LLM({"general.architecture": "qwen2", "tokenizer.chat_template": "<|im_start|>{{ m }}<|im_end|>"})


def test_detection():
    assert uses_harmony(GPT_OSS) and uses_harmony(HARMONY_TEMPLATE)
    assert not uses_harmony(CHATML) and not uses_harmony(_LLM({})) and not uses_harmony(object())


def test_harmony_prompt_opens_the_final_channel():
    out = format_raw_prompt(GPT_OSS, "Objective: read x")
    assert out.startswith("<|start|>system<|message|>") and "<|start|>user<|message|>Objective: read x<|end|>" in out
    assert out.endswith("<|start|>assistant<|channel|>final<|message|>")
    assert format_raw_prompt(GPT_OSS, out) == out, "already-wrapped prompts must not be double-wrapped"


def test_other_models_are_unchanged():
    for llm in (CHATML, _LLM({}), object()):
        assert format_raw_prompt(llm, "User: hi\nMorrigan:") == "User: hi\nMorrigan:"


def test_every_local_completion_goes_through_the_formatter():
    """Each raw ``llm.create_completion(prompt, ...)`` on the agent path must format its prompt."""
    sites, bad = 0, []
    for rel in ("services/llm/inference_router.py", "services/llm/gbnf_grammar.py"):
        tree = ast.parse((AGENT_DIR / rel).read_text(encoding="utf-8"))
        for n in ast.walk(tree):
            if isinstance(n, ast.Call) and getattr(n.func, "attr", "") == "create_completion":
                sites += 1
                first = n.args[0] if n.args else None
                if not (isinstance(first, ast.Call) and getattr(first.func, "id", "") == "format_raw_prompt"):
                    bad.append(f"{rel}:{n.lineno}")
    assert sites >= 3, f"PROBE BROKEN: only {sites} create_completion sites found"
    assert not bad, f"raw prompt sent without format_raw_prompt(): {bad}"


def test_harmony_end_tokens_stop_generation():
    from services.llm.llm_gateway import get_stop_sequences

    stops = get_stop_sequences()
    assert "<|return|>" in stops and "<|end|>" in stops


def test_observation_mode_never_discourages_reading():
    src = (AGENT_DIR / "services" / "agent" / "llm_decision.py").read_text(encoding="utf-8")
    block = src[src.index("if not explicit_action:"):src.index("observation_hint failed")]
    assert 'prefer action=\\"reason\\"' not in block, "the new-operator hint must not steer away from read-only tools"
    assert "read_file" in block, "the hint must say reading/inspecting is fine"
