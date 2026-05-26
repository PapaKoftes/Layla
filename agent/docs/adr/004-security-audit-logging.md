# ADR-004: Security Audit Logging

**Status:** Accepted  
**Date:** 2026-05-25  
**Context:** Security-sensitive actions (tool denials, approval escalations, sandbox violations) were logged to the general logger with no structured format or queryable store.

## Decision

Add `services/observability/security_audit.py` with:

1. Ring buffer (maxlen=500) for in-memory security events
2. Structured event types: `approval_escalation`, `action_denied`, `protected_file_attempt`, `dangerous_tool_usage`, `policy_bypass_attempt`, `sandbox_violation`
3. Fire-and-forget pattern: all log functions wrapped in try/except
4. Query API: `get_recent_security_events(n)`, `get_security_summary()`
5. REST endpoints: `GET /metrics/security`, `GET /metrics/observability`

Integration points:
- `agent_safety.py`: logs `action_denied` on planning strict refusal and allowlist refusal
- `tool_dispatch.py`: logs `policy_bypass_attempt` when bypass is active

## Consequences

- Security events are queryable via API without parsing log files.
- Ring buffer prevents unbounded memory growth.
- No performance impact: fire-and-forget, no I/O on hot path.
- Future: persist to SQLite for cross-session audit trail.
