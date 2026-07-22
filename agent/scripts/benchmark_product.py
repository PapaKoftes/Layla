#!/usr/bin/env python3
"""End-to-end PRODUCT benchmark for Layla — measures what a user actually experiences.

The other harnesses score pieces in isolation: benchmark_coding.py (model pass@1),
model_benchmark.py (raw tok/s), benchmark_suite.py (embedding/reranker/vector latency).
None of them exercise the real /agent pipeline (router -> decision loop -> reason/tool ->
polish -> stream). This one does: it drives the running server with a curated battery and
scores the dimensions that decide whether the product is good, so results are comparable
across models, configs, and hardware.

Dimensions (why each matters):
  • correctness   — does it get checkable answers right (code runs, math, facts, exact-echo)?
  • hygiene       — does the reply leak internal scaffolding? ([TOOL:/[REFUSED:/[EARNED_TITLE:,
                    raw tool-result JSON, greeting loops, role-play "User:"/"You:" turns).
                    These are real regressions we've hit; a product that leaks them is broken.
  • routing       — did a self-contained question STREAM a direct answer, or thrash tools to
                    the limit ("Stopped after maximum tool calls")?
  • latency       — first-token seconds + tokens/sec + total turn seconds (cold vs warm).

Usage:
    # start the server first (uvicorn / launcher), then:
    python scripts/benchmark_product.py --url http://localhost:8016
    python scripts/benchmark_product.py --url http://localhost:8016 --out benchmarks/scorecard.json
    python scripts/benchmark_product.py --list          # print the battery and exit
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import time
import urllib.request
import uuid
from pathlib import Path
from typing import Any, Callable

# Windows consoles default to cp1252 and choke on non-ASCII; force UTF-8 so the scorecard prints.
try:
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
except Exception:
    pass

# -- Battery --------------------------------------------------------------------
# Each case: id, category, prompt, and an optional check(reply)->bool for correctness.
# Cases with check=None are scored on hygiene/latency/routing only.

def _runs_python(code_extractor: Callable[[str], str], tests: str) -> Callable[[str], bool]:
    """Return a checker that extracts code from the reply and runs `tests` against it."""
    def _check(reply: str) -> bool:
        code = code_extractor(reply)
        if not code:
            return False
        prog = code + "\n\n" + tests + "\n"
        try:
            r = subprocess.run(
                [sys.executable, "-c", prog],
                capture_output=True, timeout=15, text=True,
            )
            return r.returncode == 0
        except Exception:
            return False
    return _check


def _extract_code(reply: str) -> str:
    """Pull the first fenced code block; fall back to the first def/class run."""
    m = re.search(r"```(?:python|py)?\s*\n(.*?)```", reply, re.DOTALL | re.IGNORECASE)
    if m:
        return m.group(1)
    m = re.search(r"((?:^|\n)(?:def |class |import |from )[\s\S]+)$", reply)
    return m.group(1) if m else ""


_NON_TOOL_ACTIONS = {"reason", "think", "none", "client_abort", "pre_read_probe"}


def executed_tools(steps: list) -> list[str]:
    """Tool actions that actually RAN this turn (probes and reasoning excluded)."""
    out = []
    for st in steps or []:
        a = (st or {}).get("action") or ""
        if a and a not in _NON_TOOL_ACTIONS:
            out.append(a)
    return out


def score_grounding(case: dict, steps: list, reply: str) -> bool | None:
    """For a case that REQUIRES a tool, did one actually execute?

    THE DIMENSION THIS HARNESS WAS MISSING, and the reason a total failure survived it. The suite
    scored correctness, hygiene, routing and latency — all from the REPLY TEXT — and never asked
    whether a tool ran. So an agent that answered every file question by inventing the contents
    scored perfectly clean: fluent prose, no marker leaks, fast, no tool thrash. It looked healthy
    while `outcome_evaluations` held 104 completed runs with zero tool steps.

    A reply that SOUNDS right about a file it never opened is the most dangerous output this product
    can produce, and it is invisible to every text-based check. Only the step trace shows it.

    THE DIMENSION IS TWO-SIDED ON PURPOSE. `requires_tool` catches fabrication; `forbids_tool`
    catches the opposite regression. Over-tool-calling was a REAL past bug here — the reason-first
    path exists because trivial chat used to thrash tools to the max-tool-calls limit — so a metric
    that only rewards tool use would push straight back into it. A one-directional quality gate does
    not measure quality, it picks a side.
    """
    need = case.get("requires_tool")
    forbid = case.get("forbids_tool")
    ran = executed_tools(steps)
    if forbid:
        return not ran
    if not need:
        return None
    if isinstance(need, str):
        return need in ran
    if isinstance(need, (list, tuple, set)):
        # A SET of acceptable tools, not "any tool at all". The first version of tool_search_symbol
        # used `requires_tool: True` and PASSED by running read_file — then answered that
        # `autonomous_run` "is not defined in the codebase", which is false. A search case satisfied
        # by a read is not measuring search; it just measures that something moved. Naming the
        # acceptable tools is what makes the case about the capability instead of about activity.
        return any(t in ran for t in need)
    return bool(ran)


BATTERY: list[dict[str, Any]] = [
    # -- grounding (correctness = a tool actually RAN, not that the prose sounds right) --
    # These exist because a dispatch bug let the agent answer every one of them fluently and
    # confidently WITHOUT opening the file, for 16 days, while every other dimension scored clean.
    {
        "id": "tool_read_named_file", "category": "grounding",
        "prompt": "Read the file README.md and tell me what the very first line of it is.",
        "requires_tool": "read_file",
        "check": None,
    },
    {
        "id": "tool_list_workspace", "category": "grounding",
        "prompt": "List the files in the current directory.",
        "requires_tool": True,
        "check": None,
    },
    {
        # NAMES the acceptable tools. With `requires_tool: True` this passed by running read_file
        # and then reporting that autonomous_run "is not defined in the codebase" — false; it is in
        # agent_loop.py. A search case a read can satisfy is not measuring search.
        "id": "tool_search_symbol", "category": "grounding",
        "prompt": "Search this codebase for where the function autonomous_run is defined.",
        "requires_tool": ("grep_code", "search_codebase", "glob_files", "search_replace"),
        "check": lambda r: "agent_loop" in (r or "").lower(),
    },
    {
        # Grounding AND correctness together: she must open the file and get a checkable fact out
        # of it. A pass here means the whole chain worked — decision, dispatch, args, execution,
        # and the answer actually reflecting what was read.
        "id": "tool_read_then_answer", "category": "grounding",
        "prompt": "Read CHANGELOG.md and tell me the single word that the very first line begins with.",
        "requires_tool": "read_file",
        "check": lambda r: "changelog" in (r or "").lower(),
    },
    # -- restraint: the OTHER half of grounding --
    # These must run NO tool. The reason-first path exists because trivial chat once thrashed tools
    # to the max-tool-calls limit; a battery that only rewards tool use would drive that back.
    {
        "id": "no_tool_trivial_math", "category": "grounding",
        "prompt": "What is 17 times 3?",
        "forbids_tool": True,
        "check": lambda r: "51" in (r or ""),
    },
    {
        "id": "no_tool_general_knowledge", "category": "grounding",
        "prompt": "In one sentence, what is a hash map?",
        "forbids_tool": True,
        "check": None,
    },
    # -- coding (correctness = code runs) --
    {
        "id": "code_reverse_string", "category": "coding",
        "prompt": "write a python function reverse_string(s) that returns the reversed string",
        "check": _runs_python(_extract_code,
            "assert reverse_string('abc') == 'cba'\nassert reverse_string('') == ''"),
    },
    {
        "id": "code_is_prime", "category": "coding",
        "prompt": "write a python function is_prime(n) that returns True if n is prime",
        "check": _runs_python(_extract_code,
            "assert is_prime(2) and is_prime(13)\nassert not is_prime(1) and not is_prime(15)"),
    },
    {
        "id": "code_fizzbuzz", "category": "coding",
        "prompt": "write a python function fizzbuzz(n) returning 'Fizz','Buzz','FizzBuzz' or str(n)",
        "check": _runs_python(_extract_code,
            "assert fizzbuzz(3)=='Fizz' and fizzbuzz(5)=='Buzz' and fizzbuzz(15)=='FizzBuzz' and fizzbuzz(7)=='7'"),
    },
    # -- factual / math (correctness = substring) --
    {"id": "fact_math", "category": "factual",
     "prompt": "what is 17 multiplied by 23? reply with just the number",
     "check": lambda r: "391" in r},
    {"id": "fact_capital", "category": "factual",
     "prompt": "what is the capital of France? one word.",
     "check": lambda r: "paris" in r.lower()},
    {"id": "fact_concept", "category": "factual",
     "prompt": "in one sentence, what is a hash map?",
     "check": lambda r: any(k in r.lower() for k in ("key", "value", "hash")) and len(r) > 20},
    # -- instruction-following (correctness = exact-ish) --
    {"id": "instr_echo", "category": "instruction",
     "prompt": "reply with exactly the single word BANANA and nothing else",
     "check": lambda r: r.strip().upper().startswith("BANANA") and len(r.strip()) < 20},
    # -- hygiene / routing probes (no correctness check; scored on leaks + routing) --
    {"id": "hygiene_hi", "category": "hygiene", "prompt": "hi", "check": None},
    {"id": "hygiene_hello", "category": "hygiene", "prompt": "hello", "check": None},
    {"id": "hygiene_thanks", "category": "hygiene", "prompt": "thanks", "check": None},
    {"id": "hygiene_capabilities", "category": "hygiene", "prompt": "what can you do", "check": None},
    {"id": "routing_howto", "category": "routing",
     "prompt": "how do I read a file in python?",
     "check": lambda r: "open(" in r or "with open" in r},
]

# -- Leak / hygiene detectors ---------------------------------------------------
_MARKER_RE = re.compile(r"\[(?:EARNED_TITLE|TOOL|REFUSED|INQUIRY|MERGE|Active aspect|SYSTEM|CONTEXT|STEP|PLAN)\b",
                        re.IGNORECASE)
_JSON_LEAK_RE = re.compile(r'\{"ok":\s*(?:true|false)|"memories"\s*:|"_deterministic')
_TURN_LEAK_RE = re.compile(r"(?:^|[.!?\n]\s*)(?:User|You|Human)\s*:", re.MULTILINE)
_TOOL_LIMIT = "maximum tool calls"


def _greeting_loop(reply: str) -> bool:
    greets = re.findall(r"\b(?:hi|hello|hey|greetings)\b", reply, re.IGNORECASE)
    return len(greets) >= 3  # >=3 greeting tokens in one reply == the loop


def score_hygiene(reply: str) -> dict[str, bool]:
    return {
        "marker_leak": bool(_MARKER_RE.search(reply)),
        "json_leak": bool(_JSON_LEAK_RE.search(reply)),
        "turn_leak": bool(_TURN_LEAK_RE.search(reply)),
        "greeting_loop": _greeting_loop(reply),
        "tool_thrash": _TOOL_LIMIT in reply.lower(),
    }


# -- Driver ---------------------------------------------------------------------
def run_case(url: str, prompt: str, timeout: float = 180.0) -> dict[str, Any]:
    """Stream one turn from /agent; return reply + latency telemetry."""
    payload = json.dumps({"message": prompt, "stream": True,
                          "conversation_id": str(uuid.uuid4())}).encode()
    req = urllib.request.Request(url.rstrip("/") + "/agent", data=payload,
                                 headers={"Content-Type": "application/json"})
    t0 = time.time()
    first_token: float | None = None
    done_steps: list = []
    n_tokens = 0
    done_content: str | None = None
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            for raw in resp:
                line = raw.decode("utf-8", "replace").strip()
                if not line.startswith("data:"):
                    continue
                try:
                    obj = json.loads(line[5:].strip())
                except Exception:
                    continue
                if obj.get("token") is not None:
                    n_tokens += 1
                    if first_token is None:
                        first_token = time.time() - t0
                if obj.get("done"):
                    done_content = obj.get("content")
                    done_steps = obj.get("steps") or []
    except Exception as e:
        return {"ok": False, "error": str(e)[:120], "reply": "", "first_token_s": None,
                "total_s": round(time.time() - t0, 1), "n_tokens": n_tokens, "tok_s": 0.0, "steps": []}
    total = time.time() - t0
    gen_window = max(0.001, total - (first_token or 0))
    return {
        "ok": True, "error": None,
        "reply": done_content or "",
        "first_token_s": round(first_token, 1) if first_token is not None else None,
        "total_s": round(total, 1),
        "n_tokens": n_tokens,
        "tok_s": round(n_tokens / gen_window, 1) if n_tokens else 0.0,
        "steps": done_steps,
    }


def _median(xs: list[float]) -> float:
    xs = sorted(x for x in xs if x is not None)
    if not xs:
        return 0.0
    n = len(xs)
    return xs[n // 2] if n % 2 else (xs[n // 2 - 1] + xs[n // 2]) / 2


def run_suite(url: str, warmup: bool = True, limit: int = 0) -> dict[str, Any]:
    if warmup:
        run_case(url, "hello")  # load the model so the first scored case isn't cold
    results = []
    battery = BATTERY[:limit] if limit and limit > 0 else BATTERY
    for case in battery:
        r = run_case(url, case["prompt"])
        hy = score_hygiene(r["reply"]) if r["ok"] else {k: False for k in
             ("marker_leak", "json_leak", "turn_leak", "greeting_loop", "tool_thrash")}
        correct = None
        if case["check"] is not None and r["ok"]:
            try:
                correct = bool(case["check"](r["reply"]))
            except Exception:
                correct = False
        clean = r["ok"] and not any(hy.values())
        grounded = score_grounding(case, r.get("steps") or [], r["reply"]) if r["ok"] else None
        results.append({
            "id": case["id"], "category": case["category"],
            "ok": r["ok"], "error": r["error"],
            "correct": correct, "clean": clean, "hygiene": hy,
            "grounded": grounded, "tools_ran": executed_tools(r.get("steps") or []),
            "first_token_s": r["first_token_s"], "total_s": r["total_s"],
            "tok_s": r["tok_s"], "n_tokens": r["n_tokens"],
            "reply_preview": (r["reply"] or "")[:160],
        })
        mark = "OK " if r["ok"] else "ERR"
        cflag = {True: "+", False: "x", None: "."}[correct]
        hflag = "clean" if clean else "LEAK:" + ",".join(k for k, v in hy.items() if v)
        gflag = {True: "grounded", False: "NO-TOOL!", None: ""}[grounded]
        print(f"  [{mark}] {case['id']:24s} correct={cflag} {hflag:24s} {gflag:9s}"
              f"ft={r['first_token_s']}s tok/s={r['tok_s']} total={r['total_s']}s")

    checkable = [r for r in results if r["correct"] is not None]
    quality = sum(1 for r in checkable if r["correct"]) / len(checkable) if checkable else 0.0
    hygiene = sum(1 for r in results if r["clean"]) / len(results) if results else 0.0
    routing = [r for r in results if r["category"] == "routing"]
    routing_ok = sum(1 for r in routing if not r["hygiene"]["tool_thrash"] and r["n_tokens"] > 0)
    routing_score = routing_ok / len(routing) if routing else 1.0
    fts = [r["first_token_s"] for r in results if r["first_token_s"] is not None]
    return {
        "results": results,
        "summary": {
            "cases": len(results),
            "errors": sum(1 for r in results if not r["ok"]),
            "quality_pass_rate": round(quality, 3),
            "quality_n": len(checkable),
            "hygiene_clean_rate": round(hygiene, 3),
            # GROUNDING: of the cases that REQUIRE a tool, how many actually ran one. Every other
            # dimension here reads the reply TEXT, so an agent inventing file contents scored a
            # clean 100% on all of them while never executing a single tool for 16 days.
            "grounding_rate": round(
                (sum(1 for r in results if r.get("grounded") is True)
                 / max(1, sum(1 for r in results if r.get("grounded") is not None))), 3),
            "grounding_n": sum(1 for r in results if r.get("grounded") is not None),
            "routing_stream_rate": round(routing_score, 3),
            "median_first_token_s": round(_median(fts), 1),
            "median_tok_s": round(_median([r["tok_s"] for r in results if r["tok_s"]]), 1),
            "median_total_s": round(_median([r["total_s"] for r in results]), 1),
        },
    }


def main() -> int:
    ap = argparse.ArgumentParser(description="Layla end-to-end product benchmark")
    ap.add_argument("--url", default="http://localhost:8016", help="running server base URL")
    ap.add_argument("--out", default="", help="write scorecard JSON here")
    ap.add_argument("--no-warmup", action="store_true", help="skip the model warm-up turn")
    ap.add_argument("--list", action="store_true", help="print the battery and exit")
    ap.add_argument("--limit", type=int, default=0, help="run only the first N cases (0 = all)")
    args = ap.parse_args()

    if args.list:
        for c in BATTERY:
            print(f"  {c['id']:24s} [{c['category']}] check={'yes' if c['check'] else 'no'}")
        print(f"\n{len(BATTERY)} cases across categories:",
              ", ".join(sorted({c['category'] for c in BATTERY})))
        return 0

    # confirm the server is reachable
    try:
        with urllib.request.urlopen(args.url.rstrip("/") + "/health", timeout=10) as r:
            _ = r.read(1)
    except Exception as e:
        print(f"ERROR: server not reachable at {args.url} ({e}). Start it first.", file=sys.stderr)
        return 2

    _n = min(args.limit, len(BATTERY)) if args.limit and args.limit > 0 else len(BATTERY)
    print(f"Layla product benchmark -> {args.url}  ({_n} cases)\n")
    report = run_suite(args.url, warmup=not args.no_warmup, limit=args.limit)
    s = report["summary"]
    print("\n-- SCORECARD ---------------------------------------------")
    print(f"  quality pass rate   : {s['quality_pass_rate']*100:.0f}%  (n={s['quality_n']} checkable)")
    print(f"  hygiene clean rate  : {s['hygiene_clean_rate']*100:.0f}%  (no marker/json/turn/loop/thrash leaks)")
    print(f"  routing stream rate : {s['routing_stream_rate']*100:.0f}%  (self-contained Qs streamed, not thrashed)")
    print(f"  grounding rate      : {s['grounding_rate']*100:.0f}%  (n={s['grounding_n']} tool-required cases ACTUALLY ran a tool)")
    print(f"  median first-token  : {s['median_first_token_s']}s")
    print(f"  median throughput   : {s['median_tok_s']} tok/s")
    print(f"  median total turn   : {s['median_total_s']}s")
    print(f"  errors              : {s['errors']}/{s['cases']}")

    if args.out:
        outp = Path(args.out)
        outp.parent.mkdir(parents=True, exist_ok=True)
        outp.write_text(json.dumps(report, indent=2), encoding="utf-8")
        print(f"\nscorecard -> {outp}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
