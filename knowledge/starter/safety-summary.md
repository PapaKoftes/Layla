# Safety summary (starter)

Layla is a **local** stack: the model and tools run on your machine. Safety is **governance**, not a guarantee that the model will never err.

**What the stack enforces**

- **Approvals** for sensitive tools (configurable).
- **Sandbox / path** constraints via config and prompts.
- **Audit** and session export (`GET /session/export`) for operator review.
- **Caps** such as `max_tool_calls`, timeouts, and resource modes (see `docs/PRODUCTION_CONTRACT.md`).

**What it does not promise**

- No claim that the LLM cannot hallucinate, refuse incorrectly, or misuse an approved action. You remain responsible for approvals and backups.

Read `docs/ETHICAL_AI_PRINCIPLES.md` and repo-root `VALUES.md` for product ethics and operator sovereignty.
