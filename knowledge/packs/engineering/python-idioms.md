---
priority: support
domain: engineering
aspect: morrigan
summary: Pythonic patterns and pitfalls: comprehensions, generators, context managers, dataclasses, typing, EAFP, GIL, pathlib.
---

# Python Idioms & Pitfalls

Write code that reads like the language intends. Idiomatic Python is usually shorter, faster, and less buggy.

## Comprehensions vs loops

Use a comprehension when building a collection from an iterable; use a loop when you're doing side effects or complex control flow.

```python
squares = [x*x for x in nums if x > 0]           # good
pairs   = {k: v for k, v in items}
uniq    = {x.id for x in objs}                    # set comp
```

- Don't nest more than two `for`/`if` clauses — extract a function or use a loop; readability wins.
- Never use a comprehension purely for side effects (`[print(x) for x in xs]` builds a throwaway list). Use a plain `for`.
- `any(...)`/`all(...)` over generator expressions short-circuit: `if any(x < 0 for x in xs)`.

## Generators & iterators

Generators produce values lazily — constant memory, work on infinite/huge streams, start yielding immediately.

```python
def read_records(path):
    with open(path) as f:
        for line in f:            # streams, doesn't load whole file
            yield parse(line)
```

- Use `yield` when you don't need the whole sequence at once, or when composing pipelines.
- `(x*x for x in xs)` is a generator expression — parens not brackets — no intermediate list.
- Generators are single-pass; iterating again yields nothing. Materialize with `list()` if you need to reuse.
- `itertools` is your friend: `chain`, `islice`, `groupby` (sort first!), `count`, `product`, `takewhile`.
- `yield from subgen` delegates to another generator.

## Context managers

Guarantee cleanup even on exception. Anything with acquire/release: files, locks, DB transactions, temp dirs, timers.

```python
with open(p) as f, lock:          # multiple in one statement
    ...

from contextlib import contextmanager
@contextmanager
def timer(label):
    t = time.perf_counter()
    try:
        yield
    finally:
        print(f"{label}: {time.perf_counter()-t:.3f}s")
```

- Prefer `with` over manual try/finally.
- `contextlib.suppress(FileNotFoundError)` instead of try/except/pass.
- `ExitStack` for a dynamic number of context managers.

## Dataclasses

For classes that are mostly data. Removes `__init__`/`__repr__`/`__eq__` boilerplate.

```python
from dataclasses import dataclass, field

@dataclass(frozen=True, slots=True)   # frozen=immutable+hashable, slots=less memory
class Point:
    x: float
    y: float
    tags: list[str] = field(default_factory=list)   # NOT tags=[]
```

- `frozen=True` for value objects (hashable, safe as dict keys).
- `slots=True` (3.10+) cuts memory and speeds attribute access.
- Use `field(default_factory=...)` for mutable defaults (see pitfall below).
- Reach for `pydantic` when you need validation/parsing at boundaries; `NamedTuple` for lightweight immutable records; `attrs` for advanced needs.

## Typing & mypy basics

```python
def greet(name: str, times: int = 1) -> str: ...
def first(xs: list[int]) -> int | None: ...      # 3.10+ union syntax
from collections.abc import Iterable, Callable, Mapping
def total(xs: Iterable[float]) -> float: ...      # accept any iterable
```

- Annotate public function signatures and dataclass fields; skip obvious locals.
- Use abstract types (`Iterable`, `Mapping`, `Sequence`) for parameters, concrete (`list`, `dict`) for returns.
- `Optional[X]` == `X | None`. Return `None` explicitly, not a bare fall-through.
- Run `mypy --strict` (or gradually) in CI; it catches whole bug classes (None misuse, wrong argument types) statically.
- `TypedDict` for dict-shaped data, `Protocol` for structural typing (duck typing with checks), `Literal` for enums of values.

## EAFP vs LBYL

Python prefers **EAFP** — "Easier to Ask Forgiveness than Permission." Try it, catch the failure.

```python
# EAFP (pythonic, no race condition)
try:
    return cache[key]
except KeyError:
    return compute(key)

# LBYL (check first) — can race, double lookup
if key in cache:            # cache could change between check and use
    return cache[key]
```

- EAFP avoids TOCTOU races (file exists check → open) and is often faster on the happy path.
- Catch the *specific* exception, narrowly scoped. Don't wrap huge blocks in try.
- LBYL is fine for cheap, race-free checks (validating an int range before use).

## Pitfalls

**Mutable default arguments** — the default is created ONCE at def time and shared across calls:

```python
def add(x, items=[]):        # BUG: items persists between calls
    items.append(x); return items
def add(x, items=None):      # FIX
    if items is None: items = []
```

**Late binding in closures/loops:**
```python
fns = [lambda: i for i in range(3)]   # all return 2
fns = [lambda i=i: i for i in range(3)]  # capture per-iteration
```

- `is` vs `==`: `is` tests identity. Use `== ` for values; `is` only for `None`/`True`/`False`/singletons.
- Modifying a list while iterating it → skipped elements. Iterate a copy (`list(xs)`) or build a new list.
- `except Exception:` swallows bugs; never bare `except:` (catches `KeyboardInterrupt`/`SystemExit`).
- Floating point: `0.1+0.2 != 0.3`. Use `math.isclose` or `decimal.Decimal` for money.

## GIL implications

CPython's Global Interpreter Lock allows only one thread to execute Python bytecode at a time.

- **CPU-bound** parallelism: threads DON'T help (GIL serializes them). Use `multiprocessing`, `concurrent.futures.ProcessPoolExecutor`, or native libs (NumPy releases the GIL) — or Python 3.13+ free-threaded build.
- **I/O-bound** concurrency: threads DO help — the GIL is released during blocking I/O. Or use `asyncio` for high-concurrency I/O (thousands of sockets) without thread overhead.
- Don't reach for `multiprocessing` on I/O work — the process overhead and serialization cost usually lose to threads/async.

## Small wins

- **pathlib** over `os.path`: `Path("a")/"b"/"c.txt"`, `.exists()`, `.read_text()`, `.glob("**/*.py")`, `.stem`, `.suffix`.
- **f-strings**: `f"{value:.2f}"`, `f"{x=}"` (debug: prints `x=5`), `f"{n:,}"` (thousands), `f"{obj!r}"` (repr).
- `enumerate(xs, start=1)` instead of manual counters; `zip(a, b)` to iterate in parallel; `dict.get(k, default)` / `collections.defaultdict` / `Counter`.
- `str.join` over `+=` in loops (O(n) vs O(n²)). Build strings from lists.
- Unpacking: `a, *rest = xs`; `x, y = y, x` swap; `first, *_, last = seq`.
