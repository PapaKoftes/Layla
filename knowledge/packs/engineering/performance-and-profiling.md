---
priority: support
domain: engineering
aspect: morrigan
summary: Measure-first, cProfile/timing, complexity intuition, caching, I/O vs CPU bound, avoiding premature optimization.
---

# Performance & Profiling

"The first rule of optimization: measure. The second rule: measure." Intuition about what's slow is wrong more often than right.

## Measure first

- **Never optimize without a profile.** The bottleneck is almost never where you think; you'll waste effort speeding up code that runs 0.1% of the time.
- Establish a baseline number and a target. "Fast enough" is a requirement, not a vibe — define the budget (e.g. p95 < 200ms).
- Optimize the **hot path** — the small fraction of code where most time goes (the 80/20 / Amdahl's law: speeding up 5% of runtime can't beat a 5% gain).
- After each change, re-measure. Confirm the speedup is real and you didn't break correctness.

## Timing quick tools

```python
import time
t = time.perf_counter(); work(); print(time.perf_counter() - t)
```
- `time.perf_counter()` for wall-clock intervals (not `time.time()`, which can jump).
- `timeit` for micro-benchmarks — it runs many loops and avoids common timing errors:
  `python -m timeit -s "setup" "code"` or `timeit.timeit(fn, number=10000)`.
- Benchmark realistic inputs and warm caches; a 3-element list tells you nothing about 3 million.
- Beware noise: run multiple times, take the min (not mean) for micro-benchmarks, control for GC and background load.

## Profiling

**cProfile** — function-level, where the time goes:
```
python -m cProfile -s cumtime script.py
```
```python
import cProfile, pstats
cProfile.run("main()", "out.prof")
pstats.Stats("out.prof").sort_stats("cumtime").print_stats(20)
```
- `tottime` = time in the function itself; `cumtime` = including callees. Sort by `cumtime` to find expensive call trees, `tottime` for hot leaf functions.
- **Line-level**: `line_profiler` (`@profile` + `kernprof -l`) pinpoints the slow line inside a function.
- **Memory**: `tracemalloc` (stdlib) or `memray`/`memory_profiler` for allocation hotspots and leaks.
- **Sampling profilers** (`py-spy`) attach to a running process with near-zero overhead — ideal for production and hangs: `py-spy top --pid <pid>`, `py-spy dump` for a stuck process's stack.

## Complexity intuition

Know the growth curve of your algorithm before micro-tuning constants.

| Big-O | Name | Feel |
|---|---|---|
| O(1) | constant | dict/set lookup, index |
| O(log n) | logarithmic | binary search, balanced tree |
| O(n) | linear | scan |
| O(n log n) | linearithmic | good sort |
| O(n²) | quadratic | nested loop over same data — dies at scale |
| O(2ⁿ), O(n!) | exponential | only tiny n |

- **Algorithmic wins dominate.** Turning an O(n²) membership check (`if x in list` inside a loop) into O(n) with a `set` beats any constant-factor tuning by orders of magnitude at scale.
- Watch for accidental quadratics: `list.__contains__` in a loop, string `+=` building, repeated `.index()`, nested loops over the same collection, N+1 DB queries.
- Choose the right structure: `set`/`dict` for membership & dedup (O(1)) vs `list` (O(n)); `collections.deque` for O(1) ends vs list `pop(0)` (O(n)); `heapq` for top-k; `bisect` for sorted inserts/search.

## I/O-bound vs CPU-bound

Diagnose which you are — the fix differs completely.
- **I/O-bound** (waiting on network/disk/DB): CPU is idle. Speed up with concurrency (`asyncio`, threads — GIL releases during I/O), batching requests, connection pooling, caching, fewer round-trips (the N+1 fix), and doing I/O in parallel rather than serially.
- **CPU-bound** (computation): threads won't help in CPython (GIL). Use `multiprocessing`/`ProcessPoolExecutor`, vectorized libraries (NumPy/pandas — C loops that release the GIL), better algorithms, or push hot code to C/Cython/Rust/`numba`.
- Measure the split: if wall-clock ≫ CPU time, you're I/O-bound.

## Caching

Trade memory for time on expensive, repeated, pure computations.
```python
from functools import lru_cache, cache
@lru_cache(maxsize=1024)
def expensive(n): ...
```
- `@lru_cache`/`@cache` (3.9+) memoizes by arguments — args must be hashable, function must be pure (same input → same output, no side effects).
- Invalidation is the hard part: cache stale data and you serve wrong answers. Bound size (`maxsize`), set TTLs, and have a clear invalidation trigger.
- Layers: in-process memoization → shared cache (Redis) → HTTP caching (ETag/Cache-Control) → CDN. Cache at the layer that saves the most work.
- Don't cache cheap or rarely-repeated work — you add complexity and memory for nothing.

## Common Python speedups (after profiling)

- Hoist invariant work out of loops; precompute lookups into a dict.
- Local variable access is faster than global/attribute — bind `func = obj.method` before a hot loop.
- `str.join(parts)` not `+=`; list/dict/set comprehensions over manual append loops (less interpreter overhead).
- Batch I/O and DB (one query with `IN`, `bulk_insert`) instead of per-item calls.
- Use generators to avoid building huge intermediate lists (memory pressure → GC → slow).
- Vectorize numeric loops with NumPy; use `pandas` operations over `iterrows()`.
- Reach for C-accelerated stdlib: `collections`, `itertools`, `bisect`, `array`.

## Avoiding premature optimization

- Correct → clear → fast, in that order. Ship readable code; optimize only measured hot spots.
- "Premature optimization is the root of all evil" — complexity added for unproven gains costs readability and breeds bugs.
- Ask before optimizing: Is it actually too slow (vs. a requirement)? Is *this* the bottleneck (profile)? Is the win worth the complexity? Will the input ever get large enough to matter?
- Sometimes the right fix is architectural (async, queue, cache, index, denormalize) not code-level. Sometimes the right fix is buying a faster machine. Match effort to payoff.
