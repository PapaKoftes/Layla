# Autonomous system (Tier-0 HTTP investigation)

Sources: [`agent/autonomous/controller.py`](../../agent/autonomous/controller.py), [`agent/autonomous/value_gate.py`](../../agent/autonomous/value_gate.py), [`agent/autonomous/policy.py`](../../agent/autonomous/policy.py), [`agent/autonomous/planner.py`](../../agent/autonomous/planner.py), [`agent/autonomous/aggregator.py`](../../agent/autonomous/aggregator.py), [`agent/routers/autonomous.py`](../../agent/routers/autonomous.py).

## Entry

- **`POST /autonomous/run`** → **`run_autonomous_task`** ([`controller.py`](../../agent/autonomous/controller.py)). Router gates: **`autonomous_mode`**, **`confirm_autonomous`**, **`goal`**; **`AutonomousTask.allow_network=False`** ([`autonomous.py`](../../agent/routers/autonomous.py)).

## Value gate

- **`evaluate_value_gate(goal)`** ([`value_gate.py`](../../agent/autonomous/value_gate.py)). If not **`ok`**, controller returns **`aggregate(..., stopped_reason="value_gate_reject", final_override`** including **`source: "blocked"`**, **`reused: False`**.

## Prefetch chain (order)

When **`autonomous_prefetch_enabled`** is true (default in [`runtime_safety.py`](../../agent/runtime_safety.py)):

1. **`try_reuse_retrieval`** — workspace **`.layla/investigation_reuse.jsonl`**
2. **`try_wiki_retrieval`** — **`.layla/wiki/*.md`**
3. **`try_chroma_retrieval`** — Chroma **`learnings`** collection via [`chroma_retrieval.py`](../../agent/autonomous/chroma_retrieval.py) + [`vector_store.py`](../../agent/layla/memory/vector_store.py)

On any hit: **`aggregate_prefetch_hit`**, **`steps_used: 0`**, planner **not** run; audit **`write_final`**.

### Retrieval layers: preference and possible “conflict” (single response)

- Within **one** request, layers are **sequential** and **mutually exclusive**: the first layer that clears its threshold wins; **`wiki`** and **`chroma`** are **not** queried after a **`reuse`** hit; **`chroma`** is **not** queried after a **`wiki`** hit.
- Layers use **different signals** (token overlap vs markdown corpus vs embedding similarity). They **can** disagree **in principle** if you imagined running all three independently; the implementation **does not** merge or vote — **earlier layer wins**.
- **`LOG_LEVEL=DEBUG`**: [`controller.py`](../../agent/autonomous/controller.py) logs which prefetch branch won and that lower layers were skipped, or logs an all-layer miss before the planner.

### Thresholds (`autonomous_*_match_threshold`)

- **`autonomous_reuse_match_threshold`**, **`autonomous_wiki_match_threshold`**, **`autonomous_chroma_match_threshold`** are independent defaults in [`runtime_safety.py`](../../agent/runtime_safety.py).
- Too **low** → more prefetch hits (risk of false positives). Too **high** → fewer hits (risk of cold planner every time).
- **Tuning** should follow **real usage** (telemetry, operator feedback); defaults are not changed casually in code without evidence.

### Embeddings and wiki growth (later / optional)

- **Chroma**: learnings use **`nomic-ai/nomic-embed-text-v1.5`** with MiniLM fallback — see [`vector_store.py`](../../agent/layla/memory/vector_store.py). Semantic mismatch on terse **code-symbol** queries is possible; optional future mitigations include **lightweight query normalization** (paths, symbols) — **not** required for current behavior.
- **Wiki**: markdown under **`.layla/wiki`** can grow over time; **optional pruning** or dedup policy is a **future** operational concern — **no** pruning subsystem today.

## Full investigation path

- **`Budget`**, **`Policy.from_config`** (tool allowlist + sandbox path checks), **`Planner.decide`** (LLM JSON tool/final), **`ContextState`** caches, **`aggregate`** on completion.

## Response **`source` / `reused`**

- Prefetch hits: **`source`** in **`reuse` | `wiki` | `chroma`**, **`reused: True`** via **`aggregate_prefetch_hit`** ([`aggregator.py`](../../agent/autonomous/aggregator.py)).
- Full run: **`source: "fresh"`**, **`reused: False`** default in **`aggregate`**.
- Value gate reject: **`source: "blocked"`**.
