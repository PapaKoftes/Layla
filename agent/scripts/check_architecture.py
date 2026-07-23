#!/usr/bin/env python
"""Architecture enforcement script — run in CI or as a pre-commit check.

Usage:
    python scripts/check_architecture.py [--strict]

Checks:
  1. Import cycle detection in critical modules
  2. Dead code detection (known dead files should stay deleted)
  3. agent_loop.py size tracking (should shrink over time)
  4. services/ flat file count (should shrink as files move to sub-packages)
  5. shared_state import count (should shrink as callers use SessionContext)
  6. All .py files compile without syntax errors

Exit code 0 = pass, 1 = fail.
"""
from __future__ import annotations

import ast
import importlib
import py_compile
import sys
from pathlib import Path

AGENT_DIR = Path(__file__).resolve().parent.parent
if str(AGENT_DIR) not in sys.path:
    sys.path.insert(0, str(AGENT_DIR))

# STRICT is the DEFAULT (CP-2). A gate that only warns is evidentially identical to no gate — this
# one had never failed AND had never run in CI. Pass --lenient to demote failures to warnings for
# local exploration; CI runs it plain, so a violation blocks the merge.
STRICT = "--lenient" not in sys.argv

passed = 0
failed = 0
warnings_list: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    global passed, failed
    if ok:
        passed += 1
        print(f"  PASS {name}")
    else:
        if STRICT:
            failed += 1
            print(f"  FAIL {name}: {detail}")
        else:
            warnings_list.append(f"{name}: {detail}")
            print(f"  WARN {name}: {detail}")


def warn(name: str, detail: str) -> None:
    warnings_list.append(f"{name}: {detail}")
    print(f"  WARN {name}: {detail}")


# A parse failure must never be silent. This checker used to `except SyntaxError: continue`, and a
# UTF-8 BOM on routers/agent.py — the 1629-line main chat router, itself a shared_state importer —
# made every AST gate skip it. The shared_state count read 15, sat exactly at its cap, and PASSED,
# while the true count was 16. A gate that silently drops the file it is meant to police reports
# health it never measured. Every AST parse now goes through here: the BOM is stripped so a byte-order
# mark can never blind the checker again, and any REMAINING parse error is recorded as a hard failure
# rather than skipped.
_parse_failures: list[str] = []


def parse_py(py_file: Path) -> "ast.Module | None":
    """Parse a .py file for an architecture gate. BOM-tolerant; loud on real syntax errors."""
    text = py_file.read_text(encoding="utf-8", errors="replace").lstrip("\ufeff")
    try:
        return ast.parse(text)
    except SyntaxError as e:
        rel = py_file.relative_to(AGENT_DIR)
        _parse_failures.append(f"{rel}: {e}")
        print(f"  FAIL parse {rel}: {e}")
        return None


# ── Check 1: Critical module imports ────────────────────────────────────

print("\n[1] Critical module imports")
CRITICAL = [
    "services.safety.agent_safety",
    "services.context.context_manager",
    "services.llm.llm_gateway",
    "services.infrastructure.resource_manager",
    "services.prompts.system_head_builder",
    "shared_state",
    "services.observability",
    "services.infrastructure.session_context",
]
for mod in CRITICAL:
    try:
        importlib.import_module(mod)
        check(f"import {mod}", True)
    except Exception as e:
        check(f"import {mod}", False, str(e)[:80])


# ── Check 2: Dead code detection ────────────────────────────────────────

print("\n[2] Dead code detection")
DEAD_CODE = [
    "services/protocols.py",
    "services/tool_generator.py",
    "ui/js/layla-app.js.bak",
]
for f in DEAD_CODE:
    path = AGENT_DIR / f
    check(f"dead code absent: {f}", not path.exists(), "file still exists")


# ── Structural ratchets — measured against reality (CP-2) ───────────────
# Each fails only if the count RISES above its recorded baseline. When a count FALLS (a later
# checkpoint migrates callers away), the printed "current" flags that the baseline can be tightened.
# Deliberately inline constants, not a separate arch-baseline.json: the check IS the assertion, and a
# JSON file + loader is more moving parts than the simplicity brief allows. Every number here was
# measured by the SAME AST logic that enforces it (post-CP-1, so no file is silently skipped).


def _iter_src(skip_tests: bool = True):
    for py_file in AGENT_DIR.rglob("*.py"):
        s = str(py_file)
        if "venv" in s or "site-packages" in s:
            continue
        if skip_tests and ("test" in py_file.name.lower()):
            continue
        yield py_file


def ratchet(name: str, current: int, baseline: int, drives: str) -> None:
    """A downward-only ceiling. Fails on rise; nudges to tighten on fall."""
    check(f"{name} <= {baseline} (current: {current})", current <= baseline)
    if current < baseline:
        warn(name, f"ratchet can tighten: {current} < {baseline} — lower the baseline ({drives})")


# Check 3: agent_loop.py size. The old cap was 1800 against an actual 1000 — pure decoration; the
# real 1000-line ceiling lives in test_architecture_boundaries. Ratcheted here to reality so the two
# gates agree and neither can drift.
print("\n[3] agent_loop.py size")
al_path = AGENT_DIR / "agent_loop.py"
if al_path.exists():
    al_lines = len(al_path.read_text(encoding="utf-8", errors="replace").splitlines())
    ratchet("agent_loop.py lines", al_lines, 1000, "extract into services/agent/")
else:
    warn("agent_loop.py", "file not found")


# Check 4: state["steps"].append sites. THE signature-defect metric: the more places that write the
# step log, the more places a tool result can be lost or a step silently skipped. CP-6 drives this to
# a single writer in turn.py; until then, no NEW append site may appear.
print("\n[4] step-log write sites")
steps_append = 0
for py_file in _iter_src():
    tree = parse_py(py_file)
    if tree is None:
        continue
    for node in ast.walk(tree):
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                and node.func.attr == "append" and isinstance(node.func.value, ast.Subscript)):
            sl = node.func.value.slice
            if isinstance(sl, ast.Constant) and sl.value == "steps":
                steps_append += 1
ratchet('state["steps"].append sites', steps_append, 49, "route through turn.record_step — CP-6")


# Check 4b: commit_turn call sites. CP-7/CP-8 collapse the argument shapes; no new call site meanwhile.
print("\n[4c] commit_turn call sites")
commit_turn_calls = 0
for py_file in _iter_src():
    tree = parse_py(py_file)
    if tree is None:
        continue
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            nm = getattr(node.func, "id", None) or getattr(node.func, "attr", None)
            if nm == "commit_turn":
                commit_turn_calls += 1
ratchet("commit_turn call sites", commit_turn_calls, 19, "one turn seam — CP-7")


# ── Check 4b: Required sub-packages exist ─────────────────────────────

print("\n[4b] Required sub-packages")
REQUIRED_SUBPKGS = [
    "services/agent",
    "services/observability",
    "services/retrieval",
    "services/planning",
    "services/skills",
    "services/tools",
    "services/context",
    "services/personality",
]
for pkg in REQUIRED_SUBPKGS:
    pkg_path = AGENT_DIR / pkg / "__init__.py"
    check(f"sub-package {pkg}/", pkg_path.exists(), "missing __init__.py")


# ── Check 5: shared_state import count ──────────────────────────────────

print("\n[5] shared_state import tracking")
ss_importers = 0
for py_file in AGENT_DIR.rglob("*.py"):
    if "venv" in str(py_file) or "site-packages" in str(py_file):
        continue
    if "test" in py_file.name.lower():
        continue
    tree = parse_py(py_file)
    if tree is None:
        continue  # recorded loudly by parse_py; the zero-parse-failures gate below fails the run
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module and "shared_state" in node.module:
            ss_importers += 1
            break
        if isinstance(node, ast.Import):
            if any("shared_state" in alias.name for alias in node.names):
                ss_importers += 1
                break
# Cap is 16, the HONEST current count. It read 15 only because a BOM on routers/agent.py — itself a
# shared_state importer — made the old inline `ast.parse` skip it (CP-1). This is a ratchet: the
# direction is DOWN as callers migrate to SessionContext. Do not raise it to admit a new importer.
check(f"shared_state importers <= 16 (current: {ss_importers})", ss_importers <= 16)


# ── Check 6: Syntax compilation ─────────────────────────────────────────

print("\n[6] Syntax check (all .py files)")
syntax_errors = 0
for py_file in AGENT_DIR.rglob("*.py"):
    if "venv" in str(py_file) or "site-packages" in str(py_file):
        continue
    try:
        py_compile.compile(str(py_file), doraise=True)
    except py_compile.PyCompileError:
        syntax_errors += 1
        if syntax_errors <= 3:
            check(f"compile {py_file.relative_to(AGENT_DIR)}", False, "syntax error")
if syntax_errors == 0:
    check("all files compile", True)
elif syntax_errors > 3:
    check(f"compile ({syntax_errors} total failures)", False)


# ── Check 7: No file was silently skipped by an AST gate ────────────────
# This is the meta-check that makes CP-1 durable: if any gate above could not parse a file, the run
# fails and names it, instead of quietly under-counting. A blind detector is worse than no detector.

print("\n[7] AST parse coverage")
check(
    f"zero files unparseable by AST gates (found: {len(_parse_failures)})",
    not _parse_failures,
    "; ".join(_parse_failures[:5]),
)


# ── Summary ─────────────────────────────────────────────────────────────

print(f"\n{'='*50}")
print(f"  Passed: {passed}")
print(f"  Failed: {failed}")
if warnings_list:
    print(f"  Warnings: {len(warnings_list)}")
print(f"{'='*50}")

sys.exit(1 if failed > 0 else 0)
