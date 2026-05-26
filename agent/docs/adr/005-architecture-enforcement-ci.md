# ADR-005: Architecture Enforcement via CI Script

**Status:** Accepted  
**Date:** 2026-05-25  
**Context:** Architecture decisions (module sizes, import boundaries, dead code) had no automated enforcement. Regressions happened silently.

## Decision

Add `scripts/check_architecture.py` with 6 checks:

1. **Critical module imports** — 8 core modules must import without error
2. **Dead code detection** — known-deleted files must stay deleted
3. **agent_loop.py size** — must stay under 1800 lines (was 4093, now 1574)
4. **services/ flat file count** — must stay under 210 (consolidation target)
5. **shared_state import count** — must stay under 15 (was 20, now 13)
6. **Syntax compilation** — all .py files must compile without errors

Run modes:
- `python scripts/check_architecture.py` — warnings only (default)
- `python scripts/check_architecture.py --strict` — exit code 1 on any failure

## Consequences

- Regressions in module size, import sprawl, and dead code are caught immediately.
- Thresholds ratchet down as improvements are made (one-way quality gate).
- Script is fast (~5s) and suitable for pre-commit hooks or CI.
- Excludes `venv/`, `site-packages/`, and test files from import counting.
