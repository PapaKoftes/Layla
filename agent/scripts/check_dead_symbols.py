#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
check_dead_symbols.py — Static symbol-liveness gate for the Layla codebase.

WHY THIS EXISTS
    This codebase's signature defect is "a complete, correct component with NO
    CALLER" — a symbol that was built and is import-able but that nothing ever
    invokes (e.g. an exported UI action never wired to a button, a helper on the
    end of a severed pipeline, a config reader no code reads). Those slip through
    every test because the dead code compiles and imports fine; only a static
    caller-graph analysis catches them. This gate is that analysis.

WHAT IT DOES
    Wraps `vulture` (jendrikseipp/vulture — a mature AST dead-code finder) and
    FAILS (exit 1) when a defined symbol has zero non-test callers AND is not in
    the committed whitelist (scripts/dead_symbols_whitelist.py). New orphans are
    caught; the existing accepted baseline is whitelisted so the gate starts GREEN.

    Run the gate:              python scripts/check_dead_symbols.py
    Regenerate the whitelist:  python scripts/check_dead_symbols.py --update-whitelist

DESIGN DECISIONS (read before changing the knobs below)
  * MIN_CONFIDENCE = 60, NOT 80. Vulture assigns 90–100% confidence to unused
    *imports/variables/unreachable code* but only 60% to unused
    *functions/classes/methods/properties* (because those could in principle be
    reached by dynamic dispatch). A dead exported function — the exact defect this
    gate exists to catch, and the case the teeth-test proves — is a 60% finding.
    Running at 80 would make the gate structurally blind to its own reason to
    exist, so we run at 60 and lean on the whitelist + exclusions to control noise.

  * GATED_TYPES = functions/classes/methods/properties only. We deliberately do
    NOT gate on:
      - unused *imports*: the repo intentionally tolerates them — ruff's F401 is
        switched OFF in pyproject.toml ("some intentional re-exports"). Gating on
        imports here would contradict that project-wide policy.
      - unused *variables* / *attributes*: local dead assignments and unset
        dataclass/pydantic fields are a different, much noisier concern with a high
        false-positive rate; out of scope for a *symbol-liveness* gate.
      - *unreachable_code*: a different defect class, and vulture cannot express it
        as a whitelist entry (it emits a bare comment), so it could never go green.

  * FRAMEWORK ENTRY POINTS are excluded, because their "caller" is a framework and
    is invisible to static analysis:
      - FastAPI/Starlette route + app handlers via IGNORE_DECORATORS (@router.*,
        @app.*).
      - The dynamic-dispatch registries layla/tools/impl/ (dispatched by name via
        getattr in the tool registry) and plugins/ (dynamically loaded). These are
        a deliberate blind spot — a dead helper *inside* those trees will not be
        caught. Everything else (routers glue, services, orchestrator, core,
        memory, shared_state, …) — where the "built but never wired" defect
        actually bites — is in scope.
      - pytest fixtures / test helpers: tests/ is excluded entirely.
      - __init__.py re-exports: vulture ignores unused imports in __init__.py
        natively, so plain re-export surfaces do not trip the gate.

  * The whitelist is name-matched (vulture's model), so a NEW orphan whose name
    already appears in the whitelist would be missed. That is an accepted, standard
    vulture limitation; unique new names are always caught.

DEGRADES GRACEFULLY
    If `vulture` is not importable the gate prints a clear notice and PASSES
    (exit 0) so a contributor without the dev extra is never hard-blocked. CI
    installs the dev extra (pyproject `[dev]`), so the gate is live there.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

AGENT_DIR = Path(__file__).resolve().parent.parent
WHITELIST_PATH = AGENT_DIR / "scripts" / "dead_symbols_whitelist.py"

# --- Knobs (see DESIGN DECISIONS above) --------------------------------------
MIN_CONFIDENCE = 60
GATED_TYPES = frozenset({"function", "class", "method", "property"})
IGNORE_DECORATORS = ["@router.*", "@app.*"]

# Paths never scanned for liveness (fnmatch globs, matched against each file path).
EXCLUDE = [
    "*/tests/*",
    "*/__pycache__/*",
    "*/build/*",
    "*/dist/*",
    "*.egg-info",
    "*/models/*",
    "*/.venv/*",
    "*/venv/*",
    "*/node_modules/*",
    "*/tools/impl/*",   # dynamic-dispatch tool registry: getattr(impl, fn_name)
    "*/plugins/*",      # dynamically loaded plugin registry
]

# During whitelist regeneration the committed whitelist must NOT suppress itself,
# or it would regenerate empty. This glob drops it from that one scan.
_WHITELIST_GLOB = "*dead_symbols_whitelist.py"


def _load_vulture():
    """Return the vulture module, or None if it isn't installed."""
    try:
        import vulture  # type: ignore
    except Exception:
        return None
    return vulture


def find_dead_symbols(vulture_mod, targets, *, exclude=None):
    """Scan `targets` and return the gated-type unused-code items.

    The committed whitelist lives inside AGENT_DIR, so when AGENT_DIR is a target
    it is scanned as part of the tree and its entries suppress the baseline
    automatically — no separate whitelist path needs to be passed.
    """
    exclude = list(EXCLUDE if exclude is None else exclude)
    v = vulture_mod.Vulture(verbose=False, ignore_decorators=IGNORE_DECORATORS)
    v.scavenge([str(t) for t in targets], exclude=exclude)
    items = v.get_unused_code(min_confidence=MIN_CONFIDENCE)
    return [it for it in items if it.typ in GATED_TYPES]


def _rel(filename: str) -> str:
    try:
        return os.path.relpath(filename, AGENT_DIR)
    except Exception:
        return filename


def _format(item) -> str:
    return f"{_rel(item.filename)}:{item.first_lineno}: {item.name}  [{item.typ}, {item.confidence}%]"


def check() -> int:
    """Run the gate over the app tree. 0 = clean/skipped, 1 = new orphan(s)."""
    vulture_mod = _load_vulture()
    if vulture_mod is None:
        print("check_dead_symbols: vulture not installed - SKIPPING "
              "(pip install vulture, or install the [dev] extra). Gate treated as pass.")
        return 0

    findings = find_dead_symbols(vulture_mod, [AGENT_DIR])
    if not findings:
        print("check_dead_symbols: OK - no dead symbols outside the whitelist.")
        return 0

    findings.sort(key=lambda it: (_rel(it.filename), it.first_lineno))
    print("check_dead_symbols: FAIL - load-bearing symbol(s) with zero non-test callers.")
    print("  (If a finding is intentional, regenerate the whitelist: "
          "python scripts/check_dead_symbols.py --update-whitelist)")
    for it in findings:
        print(f"  {_format(it)}", file=sys.stderr)
    print(f"\n{len(findings)} new dead symbol(s).", file=sys.stderr)
    return 1


def generate_whitelist() -> int:
    """Regenerate scripts/dead_symbols_whitelist.py from the current tree."""
    vulture_mod = _load_vulture()
    if vulture_mod is None:
        print("check_dead_symbols: cannot regenerate whitelist - vulture is not installed.",
              file=sys.stderr)
        return 2

    # Exclude the whitelist itself so it does not suppress the very findings we
    # are trying to capture.
    items = find_dead_symbols(vulture_mod, [AGENT_DIR], exclude=EXCLUDE + [_WHITELIST_GLOB])
    items.sort(key=lambda it: (_rel(it.filename), it.first_lineno))

    header = [
        # Blanket lint-ignore: a vulture whitelist is bare `name` / `_.attr` references,
        # which is intentionally not lint-clean Python (F821 undefined-name, etc.).
        "# ruff: noqa",
        "# dead_symbols_whitelist.py — AUTO-GENERATED baseline for check_dead_symbols.py.",
        "#",
        "# Each line names a symbol that is currently unreferenced by static analysis but",
        "# is accepted for now. These are the EXISTING baseline, not an endorsement — the",
        "# gate's job is to catch NEW orphans, not to force fixing every one of these today.",
        "#",
        "# Vulture consults this file by NAME: a bare `name` or `_.attr` counts as a use and",
        "# suppresses that finding. Entries here largely reflect this codebase's heavy",
        "# dynamic-dispatch / scaffolding surface (registry-called helpers, shared-state",
        "# setters, etc.). Some may be genuinely dead and worth removing — see the report",
        "# from the session that introduced this gate.",
        "#",
        "# DO NOT hand-edit. Regenerate after intentionally adding/removing dead code:",
        "#     python scripts/check_dead_symbols.py --update-whitelist",
        "",
    ]
    body = [it.get_whitelist_string() for it in items]
    WHITELIST_PATH.write_text("\n".join(header + body) + "\n", encoding="utf-8")
    print(f"check_dead_symbols: wrote {len(body)} whitelist entr"
          f"{'y' if len(body) == 1 else 'ies'} to {_rel(str(WHITELIST_PATH))}")
    return 0


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if "--update-whitelist" in argv:
        return generate_whitelist()
    if argv and argv[0] in ("-h", "--help"):
        print(__doc__)
        return 0
    return check()


if __name__ == "__main__":
    raise SystemExit(main())
