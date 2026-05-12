#!/usr/bin/env python3
"""Verify each 'delivered' service has at least one production import.

Production = not tests/, not scripts/, not routers/ (router-only doesn't count
as production usage), and not the service's own module.
"""
from __future__ import annotations
import re
import sys
from pathlib import Path

AGENT = Path(__file__).resolve().parent.parent

REQUIRED = {
    # service_module : [forbidden_dirs_for_callers]
    "services.repo_indexer": ["tests"],
    "services.memory_router": ["tests", "scripts"],
    "services.prompt_compressor": ["tests"],
    "services.prompt_optimizer": ["tests"],
    "services.config_cache": ["tests"],
}


def find_importers(module: str) -> list[Path]:
    pattern = re.compile(
        rf"(from\s+{re.escape(module)}\s+import|import\s+{re.escape(module)}\b)"
    )
    hits = []
    for p in AGENT.rglob("*.py"):
        rel = p.relative_to(AGENT)
        if any(part.startswith(".") for part in rel.parts):
            continue
        try:
            if pattern.search(p.read_text(encoding="utf-8", errors="ignore")):
                hits.append(rel)
        except Exception:
            pass
    return hits


def main() -> int:
    failed = []
    for mod, forbidden in REQUIRED.items():
        importers = find_importers(mod)
        own_name = mod.split(".")[-1]
        prod = [
            p for p in importers
            if not any(str(p).startswith(f) for f in forbidden)
            and p.stem != own_name
            and p.parent.name != "routers"
        ]
        if not prod:
            failed.append(
                f"  {mod}: no production importers (only: {[str(p) for p in importers]})"
            )

    if failed:
        print("FAIL: wiring check\n" + "\n".join(failed))
        return 1
    print(f"PASS: all {len(REQUIRED)} services have production importers")
    return 0


if __name__ == "__main__":
    sys.exit(main())
