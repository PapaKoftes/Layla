---
priority: support
domain: coding
aspects: morrigan
---

# asyncio patterns

- `asyncio.gather` for independent tasks; cap concurrency with semaphores (see coordinator parallel path).
- Do not block the event loop: CPU or SQLite-heavy work belongs in threads or dedicated workers.
