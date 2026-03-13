---
priority: core
domain: engineering
aspect: morrigan
---

# Engineering Principles — Morrigan's Reference

These are not rules. They are patterns that survive contact with reality.

---

## Clean Code

**Functions do one thing.** If you need "and" to describe what a function does, it does two things. Split it.

**Names explain intent, not mechanism.** `calculate_tax(amount)` is better than `process_number(n)`. `user_has_valid_session()` is better than `check_user()`. The name is documentation.

**Magic numbers are lies.** `60 * 60 * 24` tells a story. `86400` tells nothing. Use named constants.

**Early returns over nesting.** Guard at the top, work in the middle, return at the end. Deeply nested logic is a sign the function is doing too much.

**Comments explain why, not what.** If the code needs a comment to explain what it does, the code should be clearer. Save comments for why a non-obvious decision was made.

---

## Architecture

**Dependency direction matters.** High-level modules should not depend on low-level modules. Both should depend on abstractions. When you violate this, changes ripple upward unpredictably.

**Separation of concerns.** The thing that knows how to store data should not know how to render it. The thing that handles HTTP should not know business rules. These separations contain change.

**Single source of truth.** Duplicated data creates synchronization problems. Duplicated logic creates divergence bugs. Find the one place where each thing lives and make everything else reference it.

**Interfaces over implementations.** Code to contracts, not to specific classes. This makes testing trivial and replacement possible.

**Prefer composition over inheritance.** Inheritance creates tight coupling and fragile hierarchies. Composition gives you the same code reuse with less coupling.

---

## Python Specifics

**Use dataclasses or Pydantic for structured data.** Dictionaries with expected keys are untested contracts. Typed structures are self-documenting and validated.

**Context managers for resource lifecycle.** `with` ensures cleanup. File handles, database connections, locks — all belong in context managers.

**Generators for large sequences.** Don't build a list of 10,000 items if you're going to iterate through them once. Generators compute lazily.

**Type hints are load-bearing documentation.** They tell future readers (including the LLM helping debug) what types are expected without having to trace execution.

**Avoid global mutable state.** Module-level globals that change at runtime are implicit dependencies that don't appear in function signatures. Pass state explicitly.

**Use `__slots__` for performance-critical classes.** Reduces memory footprint and speeds up attribute access in hot paths.

**`pathlib.Path` over string paths everywhere.** Handles OS path differences, provides rich path manipulation API, integrates cleanly with file operations.

---

## Debugging Methodology

**Read the error completely before acting.** The last line of a Python traceback is the error. The lines above it are the call stack. Read from bottom to top. Most people act on the last line without reading the context.

**Reproduce before fixing.** If you can't reproduce it, you don't understand it. If you don't understand it, your fix is a guess.

**Simplify until it breaks.** Remove code until the bug disappears, then add back until it reappears. What you just added is suspect.

**Check your assumptions.** Print the actual values, not the ones you think they should be. Most bugs are assumptions that turned out to be wrong.

**Git bisect for regressions.** When something worked and now doesn't, git bisect finds the commit that broke it in O(log n) steps.

**Read the source, not just the docs.** When a library behaves unexpectedly, reading its source is faster than reading ten Stack Overflow answers.

---

## Performance

**Profile before optimizing.** Premature optimization is when you guess. Profile first. The bottleneck is rarely where you expect it.

**O(n²) disguised as O(n).** A loop inside a function called inside another loop is O(n²). Track algorithmic complexity, not just line count.

**I/O is the ceiling.** Memory access is fast. Disk is slow. Network is slower. Database round-trips multiply. Batch and cache at the I/O boundary.

**Cache what's expensive.** `functools.lru_cache`, Redis, in-memory dicts — pick by TTL and invalidation requirements. The best cache is the one you don't have to think about.

**Connection pools, not new connections.** Creating a database connection per request is the single fastest way to kill a web service under load.

---

## System Design

**Design for failure.** What happens when the database is slow? When the API is down? When the queue is full? The failure cases should be first-class design decisions, not afterthoughts.

**Idempotency where it counts.** Operations that can be retried safely without side effects (idempotent) are much easier to reason about under failure. Design your mutations to be idempotent.

**Back-pressure.** When a consumer can't keep up with a producer, something has to give. Decide in advance what that is: drop, queue, or block. Not deciding is deciding (badly).

**Observability is not optional.** You will not know what your system is doing under load without logging, metrics, and tracing. Instrument before you need it.

**Simple beats clever.** The system that's easier to understand is easier to debug, extend, and operate. Clever solutions that save 10% performance at the cost of 200% comprehension are a bad trade.
