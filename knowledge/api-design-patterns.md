---
priority: core
domain: backend
aspects: Morrigan, Nyx
difficulty: intermediate
related: security-engineering-basics.md, observability-operations.md
---

# API design patterns

## REST semantics (practical)

- `GET` is **safe** and **idempotent**.
- `POST` creates or triggers work (not idempotent unless you design it so).
- `PUT` replaces a resource (idempotent).
- `PATCH` partially updates (idempotent if updates are).
- `DELETE` removes (idempotent).

## Idempotency

For actions that can be retried (network failures), add an idempotency key:

- Client sends `Idempotency-Key: <uuid>`
- Server stores the first result for that key and replays it

## Pagination

- Prefer cursor pagination over offset for large datasets.
- Return:
  - `items`
  - `next_cursor` (or `null`)
  - `has_more`

## Versioning

- Prefer URL versioning for major changes: `/v1/...`, `/v2/...`
- Keep versions stable; don’t silently change response shapes.

## Error shape

Keep errors consistent and machine-readable:

- `ok: false`
- `error: <code>`
- `message: <human>`
- optional `details` dict

## Observability

- Add request IDs.
- Log structured fields: endpoint, latency, status, error_code.
- Consider rate limiting on abuse-prone endpoints.

---
priority: core
domain: api
aspects: morrigan, nyx
difficulty: intermediate
related: observability-operations.md, security-engineering-basics.md
---

## API design patterns (REST-ish, pragmatic)

### Resource modeling
- Use **nouns** for resources (`/projects`, `/conversations/{id}`).
- Use sub-resources for contained objects (`/projects/{id}/goals`).

### Idempotency
- `GET`, `PUT`, `DELETE` should be idempotent.
- For “create” operations that might retry, consider **idempotency keys**.

### Pagination
- Prefer **cursor-based** pagination for large lists.
- If using offset/limit, document stability guarantees.

### Versioning
- Version at the **URL** or **header**, but pick one and be consistent.
- Avoid breaking changes; add fields rather than changing semantics.

### Error shape
- Provide machine-parseable fields:
  - `ok: false`
  - `error: <code>`
  - `message: <human>`
- Avoid leaking internals; log details server-side.

