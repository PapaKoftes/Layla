#!/usr/bin/env python
"""Liveness dashboard — which load-bearing effects have actually fired (CP-3).

REPORT-ONLY. This is not a gate and never exits non-zero on a zero count: this is a single-user
machine and "not used this week" is a legitimate reason for an effect to sit at 0. It exists to make
the signature defect — a correct component that nobody drives — visible instead of discovered by
accident sixteen days later.

    python scripts/check_liveness.py

An effect at count 0 is a question, not a verdict: "has the tool pipeline run at all since install?"
is exactly the question that went unasked for two weeks.
"""
from __future__ import annotations

import sys
from pathlib import Path

AGENT_DIR = Path(__file__).resolve().parent.parent
if str(AGENT_DIR) not in sys.path:
    sys.path.insert(0, str(AGENT_DIR))


def main() -> int:
    from services.observability import liveness

    snap = liveness.snapshot()
    print("\nLiveness — load-bearing effects\n" + "=" * 60)
    zero = 0
    for effect, rec in snap.items():
        count = rec.get("count", 0)
        when = rec.get("last_fired_at") or "never"
        flag = "  " if count > 0 else "!!"
        if count == 0:
            zero += 1
        print(f"  {flag} {effect:<24} count={count:<6} last={when}")
        if not rec.get("known", True):
            print(f"       ^ unregistered — a rename may have left a ghost effect")
    print("=" * 60)
    if zero:
        print(f"  {zero} effect(s) have NEVER fired. On a fresh install that is expected; after real")
        print("  use it means a load-bearing path is dead. This is a signal, not a failure.")
    else:
        print("  every registered effect has fired at least once.")
    # Always exit 0 — report-only by design.
    return 0


if __name__ == "__main__":
    sys.exit(main())
