---
priority: support
domain: coding
aspects: morrigan
---

# Error handling

- Catch specific exceptions; use bare `except Exception` only with logging and safe fallback.
- User-facing messages: short, actionable; log stack traces at `debug` when noisy.
