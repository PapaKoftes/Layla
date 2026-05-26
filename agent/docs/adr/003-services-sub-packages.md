# ADR-003: Services Directory Sub-Package Consolidation

**Status:** Accepted  
**Date:** 2026-05-26  
**Context:** `services/` contained 205+ flat Python files. Finding related code required scanning alphabetically. No architectural boundaries between subsystems.

## Decision

Group related files into sub-packages with backward-compatibility shims:

| Sub-package | Files moved | Theme |
|-------------|-------------|-------|
| `services/agent/` | 11 files | Agent loop decomposition modules |
| `services/observability/` | 3 files | Metrics, tracing, security audit |
| `services/planning/` | 11 files | Plan creation, execution, governance |
| `services/skills/` | 6 files | Skill registry, manifest, sandbox |
| `services/tools/` | 8 files | Tool policy, validation, preflight |
| `services/reasoning/` | 4 files | Research utilities |
| `services/retrieval/` | 2 files | Retrieval + lens refresh |
| `services/infrastructure/` | 2 files | Hardware probe, background worker |

Each original file location retains a one-line shim:
```python
"""Backward compatibility -- module moved to services/<pkg>/<name>.py"""
from services.<pkg>.<name> import *  # noqa: F401,F403
```

## Consequences

- Flat file count drops from 205 to ~160 (shims remain but are trivial).
- Related code is co-located: `services/planning/` has everything plan-related.
- All existing `from services.plan_schema import ...` imports keep working via shims.
- New code should import from the sub-package directly.
- CI check (`scripts/check_architecture.py`) enforces the flat file ceiling.
