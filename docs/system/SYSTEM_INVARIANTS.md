# System invariants (derived from code)

## Process / platform

- **Python**: [`main.py`](../../agent/main.py) exits on Python **≥ 3.13** unless **`LAYLA_ALLOW_UNSUPPORTED_PYTHON`** is **`1`/`true`/`yes`**.

## Tier-0 autonomous (`POST /autonomous/run`)

- **`AutonomousTask.allow_network=False`** set in [`routers/autonomous.py`](../../agent/routers/autonomous.py).
- Prefetch and investigation paths must not introduce shell execution or writes except wiki export paths explicitly gated in [`controller.py`](../../agent/autonomous/controller.py).

## Pending approvals

- TTL minimum **60 seconds** on append in **`_write_pending`** ([`agent_loop.py`](../../agent/agent_loop.py)); config **`approval_ttl_seconds`** overrides base TTL.

## Tool registry startup

- **`validate_tools_registry`** requires **`len(TOOLS) >= 50`** ([`layla/tools/registry.py`](../../agent/layla/tools/registry.py)).

## Response shape (Tier-0 aggregator)

- **`aggregate`** sets **`source`** to **`fresh`** and **`reused`** false by default; prefetch overrides **`source`** to **`reuse` | `wiki` | `chroma`** and **`reused`** true ([`aggregator.py`](../../agent/autonomous/aggregator.py)).
- Value gate failure sets **`source: blocked`** ([`controller.py`](../../agent/autonomous/controller.py)).

## Chroma cosine distance convention

- Similarity derived as **`1.0 - distance`** where Chroma returns distances for cosine space — see [`vector_store.py`](../../agent/layla/memory/vector_store.py) (`get_knowledge_chunks` pattern).
