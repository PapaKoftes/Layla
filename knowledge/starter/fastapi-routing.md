---
priority: support
domain: coding
aspects: morrigan
---

# FastAPI routing notes

- Use `APIRouter` per area; mount in `main.py` with `include_router`.
- Blocking work: `await asyncio.to_thread(fn, ...)`.
- Return `JSONResponse` for errors with stable `{ "ok": false, "error": "..." }` shapes when the UI depends on it.
