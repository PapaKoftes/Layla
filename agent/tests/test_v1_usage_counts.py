"""/v1 usage token counts must be REAL (cached tiktoken), not the old len(text.split()) word-split
fabrication that broke any client-side cost/token accounting."""
import sys
from pathlib import Path

AGENT_DIR = Path(__file__).resolve().parent.parent
if str(AGENT_DIR) not in sys.path:
    sys.path.insert(0, str(AGENT_DIR))
from routers.openai_compat import _usage_block  # noqa: E402


def test_usage_is_real_tokens_not_word_split():
    prompt = "Write a Python function that returns the nth Fibonacci number."
    completion = "def fib(n):\n    a, b = 0, 1\n    for _ in range(n):\n        a, b = b, a + b\n    return a"
    u = _usage_block(prompt, completion)
    assert u["prompt_tokens"] > 0 and u["completion_tokens"] > 0
    assert u["total_tokens"] == u["prompt_tokens"] + u["completion_tokens"]
    # Code tokenizes to MANY more tokens than whitespace words — proves it's not a word split.
    assert u["completion_tokens"] > len(completion.split())


def test_usage_handles_empty():
    u = _usage_block("", "")
    assert u == {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
