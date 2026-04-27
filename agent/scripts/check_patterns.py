# -*- coding: utf-8 -*-
"""
check_patterns.py â Scan for known bug patterns in the Layla codebase.

Each check targets a specific class of bug that has actually caused production
issues in this repo. Checks are regex or AST-free (plain text scan) to stay
fast and dependency-free.

Usage:
    python scripts/check_patterns.py [--path agent/]
    echo $?   # 0 = clean, 1 = issues found

Add new checks at the bottom following the same pattern.
"""
from __future__ import annotations
import re
import sys
import json
from pathlib import Path

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
REPO_ROOT = Path(__file__).resolve().parent.parent
SKIP_DIRS = {"venv", ".venv", "__pycache__", ".git", "node_modules", "models"}

# ---------------------------------------------------------------------------
# Infrastructure
# ---------------------------------------------------------------------------

class Issue:
    def __init__(self, check: str, file: Path, line: int, snippet: str, note: str):
        self.check = check
        self.file = file
        self.line = line
        self.snippet = snippet.strip()[:120]
        self.note = note

    def __str__(self):
        rel = self.file.relative_to(REPO_ROOT)
        return f"  [{self.check}] {rel}:{self.line}\n    {self.snippet}\n    ^ {self.note}"


def py_files(root: Path):
    for f in root.rglob("*.py"):
        if not any(p in f.parts for p in SKIP_DIRS):
            yield f


def lines_of(path: Path):
    try:
        return path.read_text(encoding="utf-8", errors="replace").splitlines()
    except Exception:
        return []


def json_files(root: Path):
    for f in root.rglob("*.json"):
        if not any(p in f.parts for p in SKIP_DIRS):
            yield f


issues: list[Issue] = []

def report(check, file, line, snippet, note):
    issues.append(Issue(check, file, line, snippet, note))


# ---------------------------------------------------------------------------
# CHECK 1: `reset=True` passed to llama-cpp create_completion
# Pattern: create_completion(..., reset=True, ...)
# Why: llama-cpp-python <=0.3.16 does not accept `reset` as a kwarg.
#      It raises TypeError silently swallowed â empty responses.
# ---------------------------------------------------------------------------
_RE_RESET_TRUE = re.compile(r"create_completion\s*\([^)]*reset\s*=\s*True")

def check_reset_kwarg():
    for f in py_files(REPO_ROOT):
        if f.name.startswith("check_"):  # skip scanner files themselves
            continue
        for i, line in enumerate(lines_of(f), 1):
            stripped = line.strip()
            if stripped.startswith("#"):  # skip comments
                continue
            if _RE_RESET_TRUE.search(line):
                report("RESET_KWARG", f, i, line,
                       "create_completion() does not accept reset= in llama-cpp 0.3.x; remove it")


# ---------------------------------------------------------------------------
# CHECK 2: Non-streaming response path missing strip_junk_from_reply
# Pattern: response_text assigned from steps/result without stripping
# Why: Raw LLM output (including ## CONTEXT echoes) gets sent to the user.
# ---------------------------------------------------------------------------
_RE_RAW_STEPS = re.compile(r'steps\[-1\]\.get\(.["\']result')
_RE_STRIP_NEARBY = re.compile(r"strip_junk_from_reply")

def check_strip_missing():
    for f in py_files(REPO_ROOT / "routers"):
        src_lines = lines_of(f)
        for i, line in enumerate(src_lines, 1):
            if _RE_RAW_STEPS.search(line):
                # Check the next 5 lines for strip_junk_from_reply
                window = "\n".join(src_lines[i - 1 : i + 5])
                if not _RE_STRIP_NEARBY.search(window):
                    report("STRIP_MISSING", f, i, line,
                           "steps[-1].get('result') assigned without strip_junk_from_reply(); echo leaks to user")


# ---------------------------------------------------------------------------
# CHECK 3: await run_in_executor before streaming loop
# Pattern: await ... run_in_executor(...) on its own line, followed within
#          15 lines by a `while True:` or `async for` consumer.
# Why: awaiting the executor before starting the consumer buffers the entire
#      response before streaming begins â defeats streaming UX.
# ---------------------------------------------------------------------------
_RE_AWAIT_EXEC = re.compile(r"await\s+.*run_in_executor")
_RE_CONSUMER = re.compile(r"\bwhile\s+True\b|async\s+for\b")

def check_await_executor():
    for f in py_files(REPO_ROOT / "routers"):
        src_lines = lines_of(f)
        for i, line in enumerate(src_lines, 1):
            if _RE_AWAIT_EXEC.search(line):
                window = "\n".join(src_lines[i : i + 15])
                if _RE_CONSUMER.search(window):
                    report("AWAIT_EXEC", f, i, line,
                           "run_in_executor awaited BEFORE consumer loop â start it in a Thread instead; "
                           "see openai_compat.py fix")


# ---------------------------------------------------------------------------
# CHECK 4: FTS5 query not quote-escaped
# Pattern: MATCH ? with argument that hasn't been wrapped in '"..."'
# Why: FTS5 treats special chars (+, -, *, etc.) as operators â crashes.
# ---------------------------------------------------------------------------
_RE_FTS_MATCH = re.compile(r'MATCH\s+\?', re.IGNORECASE)
_RE_FTS_ESCAPE = re.compile(r'_fts_q|\.replace\s*\(.*["\']["\']["\']|replace\(.*\+\s*["\']"')  # common escape patterns

def check_fts_escape():
    for f in py_files(REPO_ROOT):
        if f.name.startswith("check_"):  # skip scanner files
            continue
        src_lines = lines_of(f)
        for i, line in enumerate(src_lines, 1):
            if line.strip().startswith("#"):
                continue
            if _RE_FTS_MATCH.search(line):
                # Check Â±6 lines around the MATCH for any escape pattern
                window = "\n".join(src_lines[max(0, i - 6) : min(len(src_lines), i + 6)])
                if not _RE_FTS_ESCAPE.search(window):
                    report("FTS_ESCAPE", f, i, line,
                           'FTS5 MATCH ? arg may not be quote-escaped; wrap with: \'"\' + q.replace(\'"\', \'""") + \'"\' ')


# ---------------------------------------------------------------------------
# CHECK 5: Streaming generator that catches ALL exceptions silently
# Pattern: except Exception: followed immediately by pass or yield ""
# Why: Masks real errors; user sees empty response with no log.
# ---------------------------------------------------------------------------
_RE_BARE_EXCEPT = re.compile(r"except\s+Exception(\s+as\s+\w+)?\s*:")
_RE_SILENT_YIELD = re.compile(r'^\s*yield\s+["\']["\']')  # only flag silent yield "", not bare pass
# Bare `pass` in except is common + often intentional (teardown, optional feature).
# We only care about silent `yield ""` in generators â that's the pattern that masks errors
# and returns empty tokens to the streaming consumer.

def check_silent_except():
    for f in py_files(REPO_ROOT / "services"):
        # Only scan inference-path files where silent yields are dangerous
        if f.name not in ("inference_router.py", "llm_gateway.py", "structured_gen.py",
                          "retrieval.py", "context_manager.py", "coordinator.py"):
            continue
        src_lines = lines_of(f)
        for i, line in enumerate(src_lines, 1):
            if _RE_BARE_EXCEPT.search(line):
                # Collect the except block (next 4 lines)
                block = src_lines[i : min(i + 4, len(src_lines))]
                block_text = "\n".join(block)
                has_yield_empty = bool(_RE_SILENT_YIELD.search(block_text))
                has_logger = "logger." in block_text
                # Only flag if yielding empty WITHOUT any logger call â truly silent
                if has_yield_empty and not has_logger:
                    report("SILENT_EXCEPT", f, i, line,
                           "Generator catches Exception, yields '' with NO logger call; "
                           "error is invisible. Add logger.exception() before yield ''.")
                    break


# ---------------------------------------------------------------------------
# CHECK 6: Completion gate retry text leaking into final response
# Pattern: `goal = goal + "\n\n[System: Your last response"` style concatenation
#          used in a loop where `text` or `response_text` is later returned.
# Why: The retry injection appends to goal; if the model echoes it back,
#      it appears verbatim in the user-visible response.
# ---------------------------------------------------------------------------
_RE_GATE_INJECT = re.compile(r'\[System:\s*Your last response')

def check_gate_injection():
    for f in py_files(REPO_ROOT):
        src_lines = lines_of(f)
        for i, line in enumerate(src_lines, 1):
            if _RE_GATE_INJECT.search(line):
                # Check there's a strip_junk_from_reply somewhere in the same file
                full_src = "\n".join(src_lines)
                if "strip_junk_from_reply" not in full_src:
                    report("GATE_INJECT", f, i, line,
                           "Completion gate retry injection present but strip_junk_from_reply not imported; "
                           "injection text can reach user")


# ---------------------------------------------------------------------------
# CHECK 7: [EARNED_TITLE:] and role prefix not stripped in strip_junk_from_reply
# Pattern: strip_junk_from_reply body missing EARNED_TITLE / aspect name patterns
# Why: Small models echo these internal decorators into user-visible replies.
# ---------------------------------------------------------------------------
def check_strip_junk_coverage():
    target = REPO_ROOT / "agent_loop.py"
    if not target.exists():
        return
    src = target.read_text(encoding="utf-8", errors="replace")
    # Find the strip_junk_from_reply function body (up to 40 lines after def)
    m = re.search(r"def strip_junk_from_reply\(.*?\n((?:.*\n){1,50})", src)
    if not m:
        return
    body = m.group(0)
    missing = []
    if "EARNED_TITLE" not in body:
        missing.append("EARNED_TITLE")
    if not re.search(r"Morrigan|Nyx|Echo|Eris|Cassandra|Lilith", body):
        missing.append("aspect role prefixes (Morrigan/Nyx/etc.)")
    if r"\[System:" not in body and "System:" not in body:
        missing.append("[System: retry injection]")
    if missing:
        lineno = src[:src.index("def strip_junk_from_reply")].count("\n") + 1
        report("STRIP_COVERAGE", target, lineno,
               "def strip_junk_from_reply(",
               f"Missing strip patterns: {', '.join(missing)}")


# ---------------------------------------------------------------------------
# CHECK 8: logits_all / scores mismatch after speculative decoding init
# Pattern: draft_model= set in Llama() kwargs without post-init scores resize
# Why: draft_model forces _logits_all=True but scores stays (n_batch, vocab)
#      â broadcast crash on every prompt longer than n_batch tokens.
# ---------------------------------------------------------------------------
_RE_DRAFT_MODEL = re.compile(r'kwargs\[.draft_model.\]')
_RE_SCORES_RESIZE = re.compile(r'scores\s*=\s*np\.ndarray|_logits_all.*scores')

def check_logits_mismatch():
    for f in py_files(REPO_ROOT / "services"):
        src_lines = lines_of(f)
        src = "\n".join(src_lines)
        if _RE_DRAFT_MODEL.search(src):
            if not _RE_SCORES_RESIZE.search(src):
                # Find the line
                for i, line in enumerate(src_lines, 1):
                    if _RE_DRAFT_MODEL.search(line):
                        report("LOGITS_MISMATCH", f, i, line,
                               "draft_model set but no post-init scores resize guard; "
                               "will crash with broadcast error on prompts > n_batch tokens")
                        break


# ---------------------------------------------------------------------------
# CHECK 9: Missing stop sequences for section headers
# Pattern: get_stop_sequences returning list without \n## entries
# Why: Small models start responses with ## CONTEXT / ## TASK echoes.
# ---------------------------------------------------------------------------
_RE_RETURN_STOP = re.compile(r"return\s*\[")

def check_stop_sequences():
    target = REPO_ROOT / "services" / "llm_gateway.py"
    if not target.exists():
        return
    src = target.read_text(encoding="utf-8", errors="replace")
    fn_match = re.search(r"def get_stop_sequences\(\).*?(?=\ndef |\Z)", src, re.DOTALL)
    if not fn_match:
        return
    body = fn_match.group(0)
    missing = []
    if r"\n## " not in body and "\\n## " not in body:
        missing.append(r'"\n## "')
    if "endoftext" not in body:
        missing.append('"<|endoftext|>"')
    if missing:
        lineno = src[:fn_match.start()].count("\n") + 1
        report("STOP_SEQ", target, lineno,
               "def get_stop_sequences():",
               f"Stop sequences may be missing: {', '.join(missing)} â small models echo section headers")


# ---------------------------------------------------------------------------
# CHECK 10: kwargs passed to function that doesn't declare them
# Pattern: stream_reason() called with budget_retrieval_depth= but signature lacks it
# Why: silently causes TypeError â empty response.
# Target: any call site passing a kwarg the callee doesn't list.
# (Lightweight: just check the known historical offenders.)
# ---------------------------------------------------------------------------
_KNOWN_KWARG_MISMATCHES = [
    # (caller_pattern, callee_file, callee_fn, missing_kwarg)
    (re.compile(r"stream_reason\s*\(.*budget_retrieval_depth"), "agent_loop.py", "stream_reason", "budget_retrieval_depth"),
]

def check_kwarg_mismatches():
    for call_re, callee_file, callee_fn, kwarg in _KNOWN_KWARG_MISMATCHES:
        callee_path = REPO_ROOT / callee_file
        if not callee_path.exists():
            continue
        callee_src = callee_path.read_text(encoding="utf-8", errors="replace")
        # Check if callee signature includes the kwarg
        fn_match = re.search(rf"def {re.escape(callee_fn)}\s*\(([^)]*)\)", callee_src)
        if fn_match and kwarg not in fn_match.group(1):
            # Find a call site
            for f in py_files(REPO_ROOT):
                for i, line in enumerate(lines_of(f), 1):
                    if call_re.search(line):
                        report("KWARG_MISMATCH", f, i, line,
                               f"{callee_fn}() called with {kwarg}= but callee signature doesn't declare it â TypeError")


# ---------------------------------------------------------------------------
# CHECK 11: Context overflow â small-model guard missing
# Pattern: heavy sections (repo_cognition, relationship_codex, golden_examples etc.)
#          injected without _small_model / n_ctx guard.
# Why: on n_ctx=4096 the full injection exceeds the window by ~2000 tokens.
# ---------------------------------------------------------------------------
_HEAVY_SECTIONS = [
    "repo_cognition", "relationship_codex", "timeline_events",
    "personal_knowledge_graph", "golden_examples", "rl_feedback",
    "reasoning_strategies", "conversation_summaries", "relationship_memory",
]
_RE_SMALL_GUARD = re.compile(r"_small_model|small_model_mode|n_ctx.*<=.*4096|4096.*n_ctx")

def check_context_overflow_guard():
    target = REPO_ROOT / "agent_loop.py"
    if not target.exists():
        return
    src = target.read_text(encoding="utf-8", errors="replace")
    src_lines = src.splitlines()
    for section in _HEAVY_SECTIONS:
        pattern = re.compile(rf'memory_sections\["{section}"\]')
        for i, line in enumerate(src_lines, 1):
            if pattern.search(line):
                # Check up to 20 lines back (guards may be on outer if-block)
                window = "\n".join(src_lines[max(0, i - 20) : i + 2])
                if not _RE_SMALL_GUARD.search(window):
                    report("CTX_OVERFLOW", target, i, line,
                           f'"{section}" injected without _small_model guard; '
                           "overflows n_ctx=4096 â add `if not _small_model:` around this block")
                break  # one report per section is enough



# ---------------------------------------------------------------------------
# CHECK 12: hardware_probe not called at model load time
# Pattern: _get_llm() / load_llm() in llm_gateway.py without apply_to_config
# Why: Without the probe, Layla uses static defaults (n_ctx=4096, n_gpu_layers=-1)
#      regardless of the actual machine -- may overflow RAM or leave GPU unused.
# ---------------------------------------------------------------------------
_RE_APPLY_TO_CONFIG = re.compile(r"apply_to_config|hardware_detect|hardware_probe")

def check_hardware_probe_hooked():
    target = REPO_ROOT / "services" / "llm_gateway.py"
    if not target.exists():
        return
    src = target.read_text(encoding="utf-8", errors="replace")
    if not _RE_APPLY_TO_CONFIG.search(src):
        report(
            "HW_PROBE_MISSING", target, 1,
            "# services/llm_gateway.py",
            "hardware_probe.apply_to_config() not called at model load time; "
            "Layla will use static defaults regardless of actual hardware. "
            "Add: cfg = apply_to_config(cfg) before building Llama() kwargs.",
        )


# ---------------------------------------------------------------------------
# CHECK 13: capability_summary not injected into system prompt
# Pattern: agent_loop.py missing hardware_probe capability_summary injection
# Why: Layla should know her own hardware limits to describe them accurately
#      and avoid promising complex work she can't complete in the context window.
# ---------------------------------------------------------------------------
_RE_CAP_SUMMARY = re.compile(r"get_capability_summary|capability_summary")

def check_capability_summary_injected():
    target = REPO_ROOT / "agent_loop.py"
    if not target.exists():
        return
    src = target.read_text(encoding="utf-8", errors="replace")
    if not _RE_CAP_SUMMARY.search(src):
        report(
            "CAP_SUMMARY_MISSING", target, 1,
            "# agent_loop.py",
            "hardware capability_summary not injected into system_instructions; "
            "Layla cannot accurately describe her own limits to the user. "
            "Add: system_instructions += hardware_probe.get_capability_summary()",
        )

# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------

def run_all():
    print("=" * 60)
    print("Layla Bug Pattern Scanner")
    print("=" * 60)

    checks = [
        ("RESET_KWARG",       check_reset_kwarg),
        ("STRIP_MISSING",     check_strip_missing),
        ("AWAIT_EXEC",        check_await_executor),
        ("FTS_ESCAPE",        check_fts_escape),
        ("SILENT_EXCEPT",     check_silent_except),
        ("GATE_INJECT",       check_gate_injection),
        ("STRIP_COVERAGE",    check_strip_junk_coverage),
        ("LOGITS_MISMATCH",   check_logits_mismatch),
        ("STOP_SEQ",          check_stop_sequences),
        ("KWARG_MISMATCH",    check_kwarg_mismatches),
        ("CTX_OVERFLOW",      check_context_overflow_guard),
        ("HW_PROBE_MISSING",  check_hardware_probe_hooked),
        ("CAP_SUMMARY_MISSING", check_capability_summary_injected),
    ]

    for name, fn in checks:
        before = len(issues)
        try:
            fn()
        except Exception as e:
            print(f"  [ERROR] check {name} raised: {e}")
        after = len(issues)
        status = "PASS" if after == before else f"FAIL ({after - before} issues)"
        print(f"  {name:<20} {status}")

    print()
    if issues:
        print(f"ISSUES FOUND: {len(issues)}")
        print()
        for iss in issues:
            print(iss)
            print()
        sys.exit(1)
    else:
        print("All checks passed.")
        sys.exit(0)


if __name__ == "__main__":
    # Allow --path override
    root_override = None
    for i, arg in enumerate(sys.argv[1:]):
        if arg == "--path" and i + 1 < len(sys.argv[1:]):
            root_override = Path(sys.argv[i + 2]).resolve()
    if root_override:
        REPO_ROOT = root_override
    run_all()
