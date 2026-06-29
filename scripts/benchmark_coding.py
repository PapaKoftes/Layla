#!/usr/bin/env python3
"""HumanEval-style pass@1 coding benchmark for the local model (REQ-74, Phase 12).

Turns "the coding is good" into a tracked number. For each problem we prompt the
local model, extract its function, run the canonical tests in a sandboxed
subprocess (with a timeout), and score pass@1. Emits a scorecard (JSON + markdown)
with model, quant, tok/s, and per-problem results.

This is a curated HumanEval/MBPP-*style* subset (self-contained, runs offline). The
official 164-problem HumanEval can be dropped into PROBLEMS later (same shape).

Usage:
    python scripts/benchmark_coding.py --model models/Qwen2.5-Coder-7B-Instruct-Q4_K_M.gguf
    python scripts/benchmark_coding.py --self-test   # score a known-good solver (no model)
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any, Callable

# --- Curated HumanEval/MBPP-style problems -------------------------------------
# Each: prompt (signature + docstring the model completes), entry_point, and a
# `check(candidate)` test that raises AssertionError on failure.
PROBLEMS: list[dict[str, str]] = [
    {
        "task_id": "below_zero",
        "prompt": 'def below_zero(operations: list[int]) -> bool:\n    """Given a list of deposit/withdrawal operations on a zero-balance account,\n    return True if the balance ever goes below zero, else False."""\n',
        "entry_point": "below_zero",
        "test": (
            "def check(c):\n"
            "    assert c([1, 2, -4, 5]) is True\n"
            "    assert c([1, 2, 3]) is False\n"
            "    assert c([1, -1]) is False\n"
            "    assert c([-1]) is True\n"
        ),
    },
    {
        "task_id": "truncate_number",
        "prompt": 'def truncate_number(number: float) -> float:\n    """Return the decimal (fractional) part of a positive float, e.g. 3.5 -> 0.5."""\n',
        "entry_point": "truncate_number",
        "test": (
            "def check(c):\n"
            "    assert abs(c(3.5) - 0.5) < 1e-6\n"
            "    assert abs(c(1.25) - 0.25) < 1e-6\n"
            "    assert abs(c(10.0) - 0.0) < 1e-6\n"
        ),
    },
    {
        "task_id": "intersperse",
        "prompt": 'def intersperse(numbers: list[int], delimiter: int) -> list[int]:\n    """Insert `delimiter` between every two consecutive elements of `numbers`."""\n',
        "entry_point": "intersperse",
        "test": (
            "def check(c):\n"
            "    assert c([], 4) == []\n"
            "    assert c([1, 2, 3], 0) == [1, 0, 2, 0, 3]\n"
            "    assert c([5], 9) == [5]\n"
        ),
    },
    {
        "task_id": "greatest_common_divisor",
        "prompt": 'def greatest_common_divisor(a: int, b: int) -> int:\n    """Return the greatest common divisor of two integers a and b."""\n',
        "entry_point": "greatest_common_divisor",
        "test": (
            "def check(c):\n"
            "    assert c(3, 5) == 1\n"
            "    assert c(25, 15) == 5\n"
            "    assert c(48, 36) == 12\n"
        ),
    },
    {
        "task_id": "is_palindrome",
        "prompt": 'def is_palindrome(text: str) -> bool:\n    """Return True if `text` reads the same forwards and backwards."""\n',
        "entry_point": "is_palindrome",
        "test": (
            "def check(c):\n"
            "    assert c('') is True\n"
            "    assert c('aba') is True\n"
            "    assert c('abba') is True\n"
            "    assert c('abc') is False\n"
        ),
    },
    {
        "task_id": "string_xor",
        "prompt": 'def string_xor(a: str, b: str) -> str:\n    """Inputs are equal-length strings of 1s and 0s. Return their bitwise XOR as a string."""\n',
        "entry_point": "string_xor",
        "test": (
            "def check(c):\n"
            "    assert c('010', '110') == '100'\n"
            "    assert c('111', '101') == '010'\n"
            "    assert c('0', '0') == '0'\n"
        ),
    },
    {
        "task_id": "sum_to_n",
        "prompt": 'def sum_to_n(n: int) -> int:\n    """Return the sum of the integers from 1 to n inclusive (0 if n < 1)."""\n',
        "entry_point": "sum_to_n",
        "test": (
            "def check(c):\n"
            "    assert c(5) == 15\n"
            "    assert c(1) == 1\n"
            "    assert c(0) == 0\n"
            "    assert c(100) == 5050\n"
        ),
    },
    {
        "task_id": "rolling_max",
        "prompt": 'def rolling_max(numbers: list[int]) -> list[int]:\n    """Return a list where each element is the maximum seen so far (running maximum)."""\n',
        "entry_point": "rolling_max",
        "test": (
            "def check(c):\n"
            "    assert c([1, 2, 3, 2, 3, 4, 2]) == [1, 2, 3, 3, 3, 4, 4]\n"
            "    assert c([4, 3, 2, 1]) == [4, 4, 4, 4]\n"
            "    assert c([]) == []\n"
        ),
    },
    {
        "task_id": "count_vowels",
        "prompt": 'def count_vowels(s: str) -> int:\n    """Count the vowels (a, e, i, o, u, case-insensitive) in s."""\n',
        "entry_point": "count_vowels",
        "test": (
            "def check(c):\n"
            "    assert c('hello') == 2\n"
            "    assert c('AEIOU') == 5\n"
            "    assert c('xyz') == 0\n"
        ),
    },
    {
        "task_id": "merge_sorted",
        "prompt": 'def merge_sorted(a: list[int], b: list[int]) -> list[int]:\n    """Merge two already-sorted ascending lists into one sorted ascending list."""\n',
        "entry_point": "merge_sorted",
        "test": (
            "def check(c):\n"
            "    assert c([1, 3, 5], [2, 4, 6]) == [1, 2, 3, 4, 5, 6]\n"
            "    assert c([], [1, 2]) == [1, 2]\n"
            "    assert c([1, 1], [1]) == [1, 1, 1]\n"
        ),
    },
]

_FENCE = re.compile(r"```(?:python)?\s*(.*?)```", re.DOTALL)


def extract_code(text: str, entry_point: str) -> str:
    """Pull the candidate function out of a model response.

    Prefer a fenced ```python block; otherwise take the raw text. Keep everything
    from the first `def `/`import`/`from` onward so stray prose is dropped.
    """
    blocks = _FENCE.findall(text or "")
    code = blocks[0] if blocks else (text or "")
    # Trim leading prose before the first code-ish line.
    lines = code.splitlines()
    start = 0
    for i, ln in enumerate(lines):
        if ln.lstrip().startswith(("def ", "import ", "from ", "class ")):
            start = i
            break
    return "\n".join(lines[start:]).strip()


def run_one(candidate_code: str, problem: dict, scratch: Path, timeout: float = 10.0) -> tuple[bool, str]:
    """Run one candidate against its tests in a sandboxed subprocess."""
    if problem["entry_point"] not in candidate_code:
        return False, "entry point not defined"
    script = (
        candidate_code
        + "\n\n"
        + problem["test"]
        + f"\n\ncheck({problem['entry_point']})\nprint('OK')\n"
    )
    f = scratch / f"cand_{problem['task_id']}.py"
    f.write_text(script, encoding="utf-8")
    try:
        r = subprocess.run([sys.executable, str(f)], capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        return False, "timeout"
    if r.returncode == 0 and "OK" in (r.stdout or ""):
        return True, "pass"
    return False, (r.stderr or r.stdout or "fail").strip().splitlines()[-1][:120] if (r.stderr or r.stdout) else "fail"


def _llama_generator(model_path: str) -> tuple[Callable[[str], tuple[str, int]], Callable[[], None]]:
    """Build a generate(prompt)->(text, n_tokens) backed by a directly-loaded GGUF.

    (The same path the friend's box runs. Swap for services.llm_gateway.run_completion
    to benchmark the full app path.)
    """
    from llama_cpp import Llama

    llm = Llama(model_path=model_path, n_ctx=4096, n_threads=4, n_gpu_layers=0,
                verbose=False, seed=42)

    def generate(prompt: str) -> tuple[str, int]:
        out = llm.create_chat_completion(
            messages=[
                {"role": "system", "content": "You are an expert Python programmer. "
                 "Respond with ONLY the complete function implementation in a single ```python code block."},
                {"role": "user", "content": prompt},
            ],
            max_tokens=384, temperature=0.0, top_k=1, seed=42,
        )
        msg = out["choices"][0]["message"]["content"]
        n = int(out.get("usage", {}).get("completion_tokens", 0))
        return msg, n

    return generate, (lambda: None)


def benchmark(generate: Callable[[str], tuple[str, int]], problems: list[dict],
              scratch: Path) -> dict[str, Any]:
    results = []
    passed = 0
    total_tokens = 0
    t0 = time.monotonic()
    for p in problems:
        gen_text, ntok = generate(p["prompt"])
        total_tokens += ntok
        code = extract_code(gen_text, p["entry_point"])
        ok, detail = run_one(code, p, scratch)
        passed += int(ok)
        results.append({"task_id": p["task_id"], "passed": ok, "detail": detail, "tokens": ntok})
    elapsed = time.monotonic() - t0
    return {
        "n": len(problems),
        "passed": passed,
        "pass_at_1": round(passed / len(problems), 4) if problems else 0.0,
        "tokens": total_tokens,
        "elapsed_s": round(elapsed, 1),
        "tok_per_s": round(total_tokens / elapsed, 2) if elapsed > 0 else 0.0,
        "results": results,
    }


def _self_test_solver(prompt: str) -> tuple[str, int]:
    """A known-good 'model' for harness self-test: returns correct solutions."""
    ep = prompt.split("(", 1)[0].replace("def ", "").strip()
    solutions = {
        "below_zero": "def below_zero(operations):\n    b=0\n    for o in operations:\n        b+=o\n        if b<0: return True\n    return False",
        "truncate_number": "def truncate_number(number):\n    return number-int(number)",
        "intersperse": "def intersperse(numbers, delimiter):\n    r=[]\n    for i,n in enumerate(numbers):\n        if i: r.append(delimiter)\n        r.append(n)\n    return r",
        "greatest_common_divisor": "def greatest_common_divisor(a,b):\n    while b: a,b=b,a%b\n    return a",
        "is_palindrome": "def is_palindrome(text):\n    return text==text[::-1]",
        "string_xor": "def string_xor(a,b):\n    return ''.join('1' if x!=y else '0' for x,y in zip(a,b))",
        "sum_to_n": "def sum_to_n(n):\n    return n*(n+1)//2 if n>0 else 0",
        "rolling_max": "def rolling_max(numbers):\n    r=[]; m=None\n    for x in numbers:\n        m=x if m is None else max(m,x); r.append(m)\n    return r",
        "count_vowels": "def count_vowels(s):\n    return sum(c.lower() in 'aeiou' for c in s)",
        "merge_sorted": "def merge_sorted(a,b):\n    return sorted(a+b)",
    }
    code = solutions.get(ep, "def _missing(): pass")
    return f"```python\n{code}\n```", len(code)


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", help="path to a .gguf model")
    ap.add_argument("--self-test", action="store_true", help="score the known-good solver (no model)")
    ap.add_argument("--out", default="", help="write the JSON scorecard here")
    args = ap.parse_args(argv)

    with tempfile.TemporaryDirectory(prefix="layla_bench_") as td:
        scratch = Path(td)
        if args.self_test:
            label = "self-test (known-good solver)"
            card = benchmark(_self_test_solver, PROBLEMS, scratch)
        else:
            if not args.model:
                print("error: --model PATH or --self-test required", file=sys.stderr)
                return 2
            label = Path(args.model).name
            generate, _close = _llama_generator(args.model)
            card = benchmark(generate, PROBLEMS, scratch)

    card["model"] = label
    print(f"\n=== Coding benchmark | {label} ===")
    print(f"pass@1: {card['pass_at_1']*100:.1f}%  ({card['passed']}/{card['n']})  "
          f"| {card['tok_per_s']} tok/s | {card['elapsed_s']}s")
    for r in card["results"]:
        print(f"  {'PASS' if r['passed'] else 'FAIL'}  {r['task_id']:28} {('' if r['passed'] else r['detail'])}")
    if args.out:
        Path(args.out).write_text(json.dumps(card, indent=2), encoding="utf-8")
        print(f"\nscorecard -> {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
