---
priority: support
domain: coding
aspects: morrigan
---

# Pytest in this repo

- Default: `cd agent && pytest tests/ -m "not slow and not e2e_ui" -q`
- Patch DB via `layla.memory.db` barrel attributes tests expect (`_conn`, `_MIGRATED`).
