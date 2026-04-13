# Onboarding assets (documentation only)

The Web UI and first-run wizard stay **clean-room**: no bundled third-party art packs. Operators who want extra visuals or sounds can fetch **licensed** assets themselves.

## Mental model (what to tell new operators)

| Surface | What it is |
|---------|------------|
| **First setup overlay** | Model + hardware — get a GGUF loaded so chat works. |
| **Library → Workspace → Knowledge** | Summaries, learnings preview, graph hints, **memory stats**, and a **recent learnings** list with delete. Distillation / auto-learn run after substantive multi-step turns; not every reply writes to long-term memory. |
| **Library → Workspace → Codex** | Your **relationship codex** at `{workspace}/.layla/relationship_codex.json` — structured notes about people/entities. Optional: set **`relationship_codex_inject_enabled`** in `runtime_config.json` so a short digest is included in context (default **off**). |
| **Library → Workspace → Memory** | Search learnings (client filter), optional Elasticsearch, file checkpoints. |
| **Chat import** | No drag-and-drop UI yet: place export JSON/JSONL **inside the sandbox**, then use tool **`ingest_chat_export_to_knowledge`** (see [RUNBOOKS.md](RUNBOOKS.md) § Add knowledge → chat exports). |

For a broader “product vision vs shipped” map, see [PRODUCT_UX_ROADMAP_VS_CURRENT.md](PRODUCT_UX_ROADMAP_VS_CURRENT.md).

**Ideas (verify license before use)**

- **SVG / icons:** CC0 sets on OpenClipart-style archives, Phosphor / Heroicons (check each license).
- **Pixel style:** Liberated Pixel Cup (LPC) guidelines and community bases (per-asset license).
- **UI sounds:** freesound.org (filter by license), or record your own.
- **Fonts:** Google Fonts / OFL families already common on the web; self-host if you ship offline.

**Policy**

- Prefer **local paths** in `runtime_config.json` for any optional binary paths.
- Do not commit large binaries without an explicit licensing decision in the repo.
