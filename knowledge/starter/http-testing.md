---
priority: support
domain: coding
aspects: morrigan
---

# HTTP testing

- Health: `GET /health` — config + DB sanity.
- Agent: `POST /agent` JSON body; streaming uses SSE `data: ` lines.
