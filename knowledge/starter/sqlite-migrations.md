---
priority: support
domain: coding
aspects: morrigan
---

# SQLite migrations (Layla)

- Forward-only: add columns with `ALTER TABLE ... ADD COLUMN IF NOT EXISTS` inside `_migrate_impl()` in `layla/memory/migrations.py`.
- Never drop columns; re-export via `layla/memory/db.py` barrel.
