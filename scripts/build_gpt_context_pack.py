#!/usr/bin/env python3
"""
Build layla-gpt-context.zip — curated markdown for GPT Projects / external LLM context.
Run from repo root: python scripts/build_gpt_context_pack.py
"""
from __future__ import annotations

import sys
import zipfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
OUT = REPO / "layla-gpt-context.zip"

# Paths relative to repo root; missing files are skipped with a stderr line.
MANIFEST = [
    "README.md",
    "AGENTS.md",
    "PROJECT_BRAIN.md",
    "ARCHITECTURE.md",
    "LAYLA_NORTH_STAR.md",
    "VALUES.md",
    "MODELS.md",
    "WORKFLOW.md",
    "docs/IMPLEMENTATION_STATUS.md",
    "docs/ETHICAL_AI_PRINCIPLES.md",
    "docs/PRODUCTION_CONTRACT.md",
    "docs/GOLDEN_FLOW.md",
    "docs/RUNBOOKS.md",
    "docs/RULES.md",
    "docs/TECH_STACK_AND_CAPABILITIES.md",
    "docs/LAYLA_PREBUILT_PLATFORM.md",
    "docs/ONBOARDING_ASSETS.md",
    "docs/PRODUCT_UX_ROADMAP_VS_CURRENT.md",
    "docs/POST_AGENT_RESPONSE_CONTRACT.md",
    "docs/CORE_LOOP.md",
]


def main() -> int:
    added = 0
    with zipfile.ZipFile(OUT, "w", zipfile.ZIP_DEFLATED) as zf:
        for rel in MANIFEST:
            p = REPO / rel
            if not p.is_file():
                print(f"skip (missing): {rel}", file=sys.stderr)
                continue
            arc = rel.replace("\\", "/")
            zf.write(p, arcname=arc)
            added += 1
    print(f"Wrote {OUT} ({added} files)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
