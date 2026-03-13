---
priority: support
domain: python
---

# Python Best Practices

## Code style and structure

- Follow PEP 8. Use `ruff` or `black` for formatting. Use type hints everywhere.
- Prefer `pathlib.Path` over `os.path` for all file operations.
- Use `dataclasses` or `pydantic` for structured data; avoid plain dicts for complex state.
- Use `__slots__` in hot-path classes to reduce memory usage.
- Prefer f-strings over `.format()` or `%` formatting.

## Imports and modules

- Standard library imports first, third-party second, local third. Blank line between groups.
- Avoid wildcard imports (`from x import *`).
- Use `TYPE_CHECKING` guard for type-only imports to avoid circular imports.
- Lazy imports (inside functions) for slow-loading modules to speed up startup.

## Error handling

- Be specific with exception types. Catch `Exception` only at the top level.
- Use `contextlib.suppress(ExceptionType)` for expected, ignorable exceptions.
- Log exceptions with `logger.exception()` (includes traceback) not just `logger.error()`.
- Use `finally` for cleanup; use context managers where possible.

## Async

- `asyncio.run()` for top-level entry points. Never call `asyncio.get_event_loop()` in new code.
- Use `asyncio.to_thread()` to run blocking code without blocking the event loop.
- Use `asyncio.gather()` for concurrent coroutines; use `asyncio.create_task()` for fire-and-forget.
- `async with`, `async for` for async context managers and iterators.
- Never call `time.sleep()` in async code — use `await asyncio.sleep()`.
- Use `anyio` when writing library code that should work with both asyncio and trio.

## Performance

- Profile before optimizing. Use `cProfile`, `line_profiler`, or `py-spy`.
- Use `__slots__` for objects created millions of times.
- `functools.lru_cache` / `functools.cache` for pure functions with repeated args.
- `collections.deque` for fast appends/pops from both ends.
- Use `bytes` not `str` for raw binary data. `memoryview` for zero-copy slicing.
- NumPy for numerical work; avoid Python loops over large arrays.

## Testing

- `pytest` over `unittest`. Use fixtures and parametrize.
- Test behavior, not implementation. Prefer integration tests over unit tests for I/O.
- Use `tmp_path` fixture for temp files. Never hardcode paths in tests.
- Mock at the boundary (network, filesystem, time) not deep inside your code.

## Logging

- Use `logging.getLogger(__name__)` per module — never configure at module level.
- Use `logging.basicConfig()` only in `__main__` entry points.
- Use structured logging (`structlog` or `python-json-logger`) for production systems.
- Log at DEBUG for detail, INFO for milestones, WARNING for recoverable issues, ERROR for failures.

## Common pitfalls

- Mutable default arguments: `def f(x=[])` is a bug. Use `def f(x=None): if x is None: x = []`.
- Late binding closures in loops: capture with `lambda i=i: ...` if needed.
- `is` vs `==`: `is` checks identity, `==` checks equality. Use `is None`, not `== None`.
- `float` precision: never compare floats with `==`. Use `math.isclose()`.
- Thread safety: `dict` and `list` operations are GIL-protected but not atomic across multiple ops. Use `threading.Lock` for compound operations.
