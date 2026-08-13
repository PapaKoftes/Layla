---
priority: support
domain: engineering
aspect: morrigan
summary: REST/HTTP semantics, resource design, pagination/errors/versioning, input validation, relational modeling & indexes.
---

# API & Data Modeling

APIs and schemas are contracts. They're expensive to change once clients depend on them, so design them deliberately.

## HTTP methods & semantics

| Method | Purpose | Safe | Idempotent | Body |
|---|---|---|---|---|
| GET | read | yes | yes | no |
| POST | create / non-idempotent action | no | no | yes |
| PUT | replace resource wholesale | no | yes | yes |
| PATCH | partial update | no | no* | yes |
| DELETE | remove | no | yes | maybe |

- **Safe** = no state change (cacheable). **Idempotent** = N identical calls ≡ 1 call's effect.
- Idempotency matters for retries: a dropped response shouldn't cause double charges. `PUT /users/5` twice is fine; `POST /charges` twice charges twice — so provide an **idempotency key** header for POST money operations.
- Don't use GET for mutations or POST for reads. Verbs in URLs (`/getUser`, `/deleteAll`) are a smell — the method is the verb.

## Status codes

- **2xx**: 200 OK, 201 Created (return `Location` + the resource), 202 Accepted (async), 204 No Content.
- **3xx**: 301/308 moved, 304 Not Modified (caching).
- **4xx (client error)**: 400 malformed, 401 unauthenticated, 403 authenticated-but-forbidden, 404 not found, 409 conflict (version/duplicate), 422 semantic validation failure, 429 rate limited (send `Retry-After`).
- **5xx (server error)**: 500 unhandled, 502/503/504 upstream/unavailable/timeout.
- Pick the specific code; don't return 200 with `{"error": ...}`. Clients rely on status for retry/caching logic. Reserve 5xx for *your* faults — bad client input is 4xx.

## Resource modeling

- Model **nouns** (resources), not actions: `/orders`, `/orders/42/items`. Plural collections.
- Nest for ownership: `/users/7/orders`; keep nesting shallow (2 levels max) — link by ID beyond that.
- Represent state transitions as sub-resources or PATCH, not RPC verbs: `POST /orders/42/cancellation` or `PATCH /orders/42 {"status":"cancelled"}`.
- Keep representations consistent: same field names, types, date format (ISO 8601 UTC) everywhere.
- Return the created/updated resource in the response so clients don't re-fetch.

## Pagination, errors, versioning

**Pagination** — never return an unbounded list.
- *Offset* (`?limit=20&offset=40`): simple, but slow and inconsistent on large/changing data (items shift between pages).
- *Cursor/keystone* (`?limit=20&cursor=<opaque>`): stable and fast for large datasets; preferred. Return `next_cursor` and don't let clients synthesize it.
- Always cap `limit`.

**Errors** — a consistent, machine-readable envelope:
```json
{ "error": { "code": "invalid_email", "message": "Email is malformed",
             "field": "email", "request_id": "req_abc" } }
```
- Stable `code` (clients switch on it), human `message`, field-level details for validation, a `request_id` for support/log correlation. Never leak stack traces or internals to clients.

**Versioning** — you'll need to make breaking changes.
- URL version (`/v1/…`) is explicit and simple; header/media-type versioning is purer but harder to test.
- **Additive changes** (new optional fields, new endpoints) are non-breaking — don't bump the version. Clients must ignore unknown fields.
- **Breaking** = removing/renaming fields, changing types, tightening validation, changing semantics. Version and support the old version during a deprecation window.

## Input validation

- **Validate at the boundary** — never trust client input. Parse into typed models (`pydantic`, marshmallow) at the edge; the interior works with validated objects.
- Check types, ranges, lengths, formats, enums, required fields; reject unknown fields or ignore them consistently.
- Whitelist allowed values, don't blacklist bad ones.
- **Never build SQL/shell/HTML by string concatenation** — parameterized queries and proper escaping prevent injection. This is non-negotiable.
- Validate on the server even if the client validates — client checks are UX, not security.
- Enforce size limits (payload, array length, string length) to prevent resource exhaustion.

## Relational modeling

**Normalization** (3NF as default): each fact in exactly one place. Eliminates update anomalies (change an address once, not in 500 rows).
- 1NF: atomic columns, no repeating groups. 2NF/3NF: non-key columns depend on the whole key and nothing but the key.
- Separate entities into their own tables; relate by keys.

**Keys & foreign keys:**
- Every table gets a primary key (surrogate `id` is usually cleaner than a natural key).
- **Foreign keys** enforce referential integrity — you can't reference a nonexistent row, and the DB blocks orphan-creating deletes (or cascades per `ON DELETE`). Declare them; don't rely on app code alone.

**Indexes:**
- Index columns you filter (`WHERE`), join on (FKs — often unindexed by default!), and sort by (`ORDER BY`).
- Composite index column order matters: `(a, b)` serves `WHERE a` and `WHERE a AND b`, not `WHERE b` alone (leftmost-prefix rule).
- Indexes speed reads but slow writes and cost storage — don't index everything. Index for actual query patterns.
- Add a unique index to enforce uniqueness constraints (email, slug).
- The classic performance bug: **N+1 queries** — loading a list then querying per-row in a loop. Fix with a join or batched `IN (...)` / eager loading.

**When to denormalize** (deliberately duplicate data):
- Read-heavy paths where joins are the bottleneck and data changes rarely (e.g. cached counts, materialized aggregates, denormalized report tables).
- Accept the cost: you must now keep copies in sync (triggers, app logic, periodic rebuild) — a source of bugs. Normalize first; denormalize only with a measured reason.
- Prefer caching, read replicas, or materialized views before hand-denormalizing schema.
