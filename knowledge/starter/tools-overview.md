# Tools overview (starter)

Layla exposes many tools from `agent/layla/tools/registry.py` (file read/write, patch, shell, browser, retrieval, etc.). Each tool declares **risk** and whether **approval** is required.

**Rules of thumb**

- Prefer **read-only** tools until you intend to change disk or run commands.
- Treat **shell** and **write** paths as privileged: approve only what you understand.
- Use **sandbox_root** / workspace settings so defaults stay inside folders you trust.

See `knowledge/tools-reference.md` in the main curated library for deeper detail.
