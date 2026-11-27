"""Put a raw completion prompt into the loaded model's own turn format when raw text breaks it.

Layla builds plain-text prompts and sends them through ``Llama.create_completion`` (no chat template). That
works for ChatML-era instruct models, but gpt-oss (OpenAI "harmony" format: Jinx, gpt-oss-20b) treats raw
text as the middle of its analysis channel. MEASURED on jinx-20b, real production decision prompts under the
real GBNF grammar: raw prompts picked the right tool in 2/6 goals (answered "I have enough context" instead
of reading a named file, copied the few-shot path ``agent/main.py``); wrapped in harmony with the final
channel open, 5/6 with the correct path. The live symptom was an agent that never ran a tool and printed
``read_file("x")`` as text.

Only harmony models are changed; every other model gets its prompt back unchanged.
"""
from __future__ import annotations

from typing import Any

# Open the FINAL channel directly: the grammar / reply goes straight into the answer, and skipping the
# analysis channel avoids hundreds of hidden reasoning tokens per call on CPU. Exactly the A/B variant.
_HARMONY_PREFIX = "<|start|>system<|message|>You are a helpful assistant.\nReasoning: low<|end|><|start|>user<|message|>"
_HARMONY_SUFFIX = "<|end|><|start|>assistant<|channel|>final<|message|>"


def uses_harmony(llm: Any) -> bool:
    """True when the loaded GGUF is a harmony-format model (gpt-oss architecture or a harmony template)."""
    try:
        md = getattr(llm, "metadata", None) or {}
        return md.get("general.architecture") == "gpt-oss" or "<|channel|>" in str(md.get("tokenizer.chat_template") or "")
    except Exception:
        return False


def format_raw_prompt(llm: Any, prompt: str) -> str:
    """Return ``prompt`` in the model's turn format (harmony models only; identity otherwise / if already wrapped)."""
    if not prompt or not uses_harmony(llm) or prompt.lstrip().startswith("<|start|>"):
        return prompt
    return _HARMONY_PREFIX + prompt + _HARMONY_SUFFIX
