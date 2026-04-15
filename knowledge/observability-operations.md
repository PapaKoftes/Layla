---
priority: core
domain: operations
aspects: Nyx, Morrigan
difficulty: intermediate
related: devops-cicd-patterns.md, api-design-patterns.md
---

# Observability and operations

## Three pillars (useful model, not a religion)

- **Logs**: discrete events (what happened, with context)
- **Metrics**: numeric time series (how often, how long, how many)
- **Traces**: request path across components (where time went)

## Structured logging

- Prefer JSON-ish structured logs over freeform strings.
- Always include:
  - timestamp (UTC)
  - level
  - request_id / correlation_id
  - component/module
  - event name / error code

## Metrics that matter

For an assistant runtime, start with:

- request latency (p50/p95/p99)
- error rate by endpoint/tool
- tool latency distribution
- queue depth / background job backlog
- memory retrieval latency
- token throughput (if available)

## SLOs (start small)

- Define 1–3 SLOs you can actually maintain.
- Example: “95% of `/agent` responses start streaming within X seconds.”

## Alerts (avoid alert fatigue)

- Alert on symptoms that require action:
  - sustained error rate
  - sustained latency regression
  - disk full
  - database locked
- Don’t alert on every spike; use windows and burn rates.

## Postmortems

- Blameless.
- Focus on:
  - what happened
  - why it happened
  - what we’ll change (code + process)

---
priority: core
domain: observability
aspects: morrigan, echo
difficulty: intermediate
related: devops-cicd-patterns.md, api-design-patterns.md
---

## Observability & operations (logs, metrics, traces)

### Logs
- Prefer **structured logs** (key/value fields).
- Use stable event names and include:
  - `component`, `action`, `duration_ms`, `ok`, `error_code`
- Don’t log secrets.

### Metrics
- Track what you can act on:
  - request rate, error rate, latency percentiles
  - tool latency, approval queue length
- Define **SLOs** (e.g. “p95 response < 2s for /health”).

### Tracing
- Trace multi-step flows (request → tool call → DB write).
- Use trace IDs to connect logs across components.

### Alerts
- Alert on symptoms (error rate, sustained latency) not raw CPU.
- Prefer fewer, high-quality alerts.

