# Tasks — backlog pointer

This file is intentionally **lightweight**. Detailed planning belongs in **`docs/ROADMAP.md`**, **`docs/MILESTONES.md`**, and issues.

## How to use

- Add **short-lived** cross-cutting themes (one line each) when a release needs a visible checklist.
- Prefer **GitHub issues / project boards** for granular work items; link them here if useful.
- Remove completed themes promptly to avoid stale docs.

## Example entries (replace with current work)

- (none — edit when cutting a release)

## Refactor backlog (non-blocking)

- **Large modules:** `agent/agent_loop.py` and `agent/layla/tools/registry.py` are intentionally monolithic for now; future splits should preserve test coverage and approval/tool gating invariants.

## Related

- **`docs/POST_AGENT_RESPONSE_CONTRACT.md`** — `POST /agent` JSON shapes (fast path vs loop vs no-model); keep in sync with [`agent/routers/agent.py`](../agent/routers/agent.py).
- **`docs/FULL_TECHNICAL_AUDIT.md`** — ground-truth system audit, parity notes, FastAPI route appendix (regenerate when routes change).
- **`docs/RELEASE_CHECKLIST.md`** — verification before publish.
- **`docs/IMPLEMENTATION_STATUS.md`** — North Star vs code map.
