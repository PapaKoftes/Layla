---
priority: support
domain: engineering
aspect: morrigan
summary: Test pyramid, behavior-not-implementation, fixtures, mocking boundaries, property tests, coverage, flakes, pytest.
---

# Testing Strategy

Tests exist to let you change code without fear. A test that breaks on every refactor but never on a real bug is negative value. Optimize for that trade-off.

## The test pyramid

```
        /\   e2e         few   — slow, brittle, high confidence, full stack
       /--\  integration some  — real boundaries (DB, API), moderate speed
      /----\ unit        many  — fast, isolated, pinpoint failures
```

- **Unit**: one function/class, no I/O, milliseconds. The bulk.
- **Integration**: real collaborators — DB, cache, HTTP client to a test server, filesystem. Catches wiring/serialization/SQL bugs unit tests can't.
- **e2e**: the whole system through its real entry point (HTTP, CLI). Few, cover critical user journeys only.

Inverted pyramid (mostly e2e) → slow suite, flaky, vague failures. Diamond/hourglass is fine for services where integration is where real bugs live.

## Test behavior, not implementation

- Assert on **observable outcomes** (return values, emitted events, persisted state, HTTP responses), not internal calls or private methods.
- Bad: `assert obj._cache_hits == 1`. Good: `assert result == expected` and second call is faster / doesn't hit the DB.
- If renaming a private method or reordering internal calls breaks a test, the test is coupled to implementation. Rewrite it against the contract.
- Test through the public API. Private helpers get covered transitively; test them directly only when the logic is complex and stable.

## What to test

- Happy path, boundaries (0, 1, many, empty, max), and error paths.
- Edge cases: None/null, empty collections, unicode, negative numbers, off-by-one, timezone/DST, concurrency where relevant.
- Regressions: every fixed bug gets a test that fails before the fix.
- Don't test the language, the framework, or trivial getters. Test *your* logic.

## Fixtures (pytest)

```python
import pytest

@pytest.fixture
def user(db):                      # fixtures compose
    return db.add(User(name="x"))

def test_rename(user):
    user.rename("y")
    assert user.name == "y"
```

- `scope="function"` (default) / `"module"` / `"session"` — widen scope for expensive setup (DB engine), keep data fixtures per-function for isolation.
- `yield` fixtures for teardown: setup before `yield`, cleanup after.
- `conftest.py` shares fixtures across a directory without imports.
- `@pytest.fixture` + `params=[...]` or `@pytest.mark.parametrize` to run one test over many inputs — prefer parametrize over loops (each case reports separately).

```python
@pytest.mark.parametrize("n,expected", [(0,1),(1,1),(5,120)])
def test_factorial(n, expected):
    assert factorial(n) == expected
```

## Mocking: boundaries only

Mock the **edges you don't own or can't control**: network, third-party APIs, clock, randomness, payment providers, email.

**Do NOT mock:**
- Code you own and could just call — use the real thing.
- The system under test (mocking it tests nothing).
- Pure functions, data structures, value objects.
- So much that the test passes even when the real integration is broken (mock theater).

Rules:
- Patch where the name is *looked up*, not where it's defined: `patch("mymodule.requests.get")` (the importing module), not `patch("requests.get")`.
- Prefer dependency injection (pass the collaborator in) over `unittest.mock.patch` monkeypatching — cleaner and less brittle.
- Prefer **fakes** (in-memory implementations, e.g. sqlite for DB, a fake clock) over mocks with hand-specified return values; fakes stay valid as the contract evolves.
- Assert on behavior, not on `mock.assert_called_with(...)` unless the call *is* the contract (e.g. "we must send the email").

## Property-based testing

Instead of hand-picked examples, assert invariants over generated inputs (`hypothesis`):

```python
from hypothesis import given, strategies as st

@given(st.lists(st.integers()))
def test_sort_idempotent(xs):
    assert sorted(sorted(xs)) == sorted(xs)
```

Great for: round-trips (`decode(encode(x)) == x`), invariants (output always sorted/non-negative), and finding edge cases you'd never enumerate. Hypothesis auto-shrinks failures to a minimal counterexample.

## Coverage: a tool, not a goal

- Coverage tells you what code *ran* during tests, not what was *verified*. 100% coverage with weak assertions catches nothing.
- Use it to find **untested branches**, not as a KPI. Chasing a % breeds assertion-free tests.
- ~80% is a healthy signal for most code; critical paths deserve near-100% with real assertions. Don't game it.
- Mutation testing (`mutmut`, `cosmic-ray`) measures assertion strength — it mutates code and checks your tests catch it. Better signal than line coverage.

## Flaky tests

A test that passes/fails without code changes. Treat as a bug — flakes erode trust in the whole suite.

Common causes: real time/`sleep`, network, shared mutable state between tests, test-order dependence, unseeded randomness, timezone, race conditions, unclosed resources.

Fixes: freeze the clock (`freezegun`), seed RNG, isolate state (fresh fixtures), no `time.sleep` — poll/await instead, make tests order-independent (`pytest -p randomly`). Quarantine persistent flakes, don't just retry-until-green.

## Pytest patterns

- `pytest -x` stop on first failure; `--lf` rerun last failures; `-k "expr"` select by name; `-q` quiet.
- `assert` directly — pytest rewrites it for rich diffs. No `assertEqual`.
- `with pytest.raises(ValueError, match="regex"):` for exceptions.
- `pytest.approx(0.3)` for float comparison.
- `tmp_path` fixture for filesystem tests; `monkeypatch` for env/attr patching; `caplog` for log assertions.
- Mark slow/integration tests: `@pytest.mark.slow`, run fast subset in the edit loop.
- One logical assertion per test where practical; the test name states the expected behavior.
