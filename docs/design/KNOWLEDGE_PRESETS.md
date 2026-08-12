# Knowledge Presets — Design (target: v1.7.5)

Status: **planned** · Owner: PapaKoftes · Supersedes the flat `knowledge/` convention

## Problem

Today `knowledge/` is a flat pile of ~35–47 curated `.md`/`.txt` docs. Two things are wrong for a fresh install:

1. **Delivery is half-dark.** Knowledge reaches the model two ways, and only one works out of the box:
   - **System-prompt injection** — `runtime_safety.load_knowledge_docs(max_bytes≈4000–6000)` concatenates docs *core → support → flavor* until the byte budget is spent. With dozens of docs, only 2–3 `priority: core` files ever make it in. Always works, but tiny.
   - **Vector RAG** — `vector_store.index_knowledge_docs()` chunks the whole folder into a searchable collection. **It is Chroma-only** (`No-op if not use_chroma` / no Chroma backend). A default CPU install falls back to the model2vec + SQLite store, where the knowledge collection is **never populated** (verified: `fallback_knowledge.sqlite` → `vectors: 0 rows`). So the broad KB is unsearchable unless the operator installs Chroma.

2. **No control.** Every operator gets the same fixed pile regardless of what they use Layla for. A CNC maker and a Python dev carry each other's docs, competing for the same 4 KB injection budget and diluting retrieval.

## Goals

- Let the operator choose **what Layla knows** via named **presets** (bundles of packs) and individual **packs**.
- Make the **broad KB actually retrievable on a default install** (fallback store, no Chroma required).
- Keep the injection budget **focused** on the enabled packs' `core` docs.
- Ship **useful, real domain knowledge** — not stubs — for the operator's actual work.
- Fully backward compatible: loose files in `knowledge/` keep working.

## Structure

```
knowledge/
  <existing loose docs>          # still scanned (back-compat, treated as an implicit "local" pack)
  packs/
    registry.json                # master list: pack id -> {title, aspect, domain, summary, docs[], bytes}
    presets.json                 # preset name -> [pack ids]
    core/                        # ALWAYS on: Layla self-knowledge (capabilities, aspects, vision)
      pack.json
      *.md
    engineering/                 # Python, APIs, testing, debugging, git, systems  (Morrigan)
    fabrication/                 # CNC, G-code, CAM, nesting, feeds/speeds, materials (Morrigan)
    embedded/                    # Arduino, microcontrollers, sensors, robotics
    research/                    # methods, source evaluation, synthesis (Nyx)
    reasoning/                   # cognitive biases, mental models, decisions (Cassandra)
    psychology/                  # non-clinical communication/collaboration (Echo)
    ethics/                      # AI safety, applied ethics (Lilith)
    creative/                    # writing, narrative, ideation (Eris)
```

### Per-doc front matter (unchanged, now required in packs)
```yaml
---
priority: core | support | flavor    # core = injection-eligible; support/flavor = RAG-only
domain: <pack id>                     # e.g. fabrication
aspect: morrigan | nyx | echo | eris | cassandra | lilith | ""
summary: one line, <=120 chars        # NEW: shown in the picker; also a retrieval hint
---
```

### `pack.json` (per pack)
```json
{
  "id": "fabrication",
  "title": "CNC & Fabrication",
  "aspect": "morrigan",
  "summary": "G-code, CAM workflow, nesting, feeds & speeds, sheet-goods and materials.",
  "docs": ["cnc-gcode-reference.md", "cam-workflow.md", "feeds-and-speeds.md", "nesting-and-sheet-goods.md", "materials-and-tooling.md"],
  "approx_bytes": 42000
}
```

### `presets.json`
```json
{
  "companion": ["core"],
  "maker":     ["core", "fabrication", "embedded", "engineering"],
  "engineer":  ["core", "engineering", "reasoning"],
  "researcher":["core", "research", "reasoning", "psychology"],
  "everything":["core", "engineering", "fabrication", "embedded", "research", "reasoning", "psychology", "ethics", "creative"]
}
```

## Config

```jsonc
// runtime_config.json
"knowledge_preset": "maker",              // shorthand; expands to packs on load
"knowledge_packs": ["core","fabrication"] // explicit override; wins over preset when present
```

- `core` is always implicitly enabled.
- Absent config → default preset `companion` (lean: just self-knowledge) so nothing surprising ships active. First-run picker sets it.

## Delivery fixes (the load-bearing work)

1. **Scope injection to enabled packs.** `load_knowledge_docs()` gains an allow-list: only inject `core`-priority docs from enabled packs (+ loose root docs). Same byte budget, now relevant.
2. **Index into the fallback store.** Add `index_knowledge_docs()` support for the model2vec + SQLite fallback collection (currently Chroma-only). Scope indexing to enabled packs. This is what makes the broad KB searchable on a default install — the single most important fix.
3. **Re-index on change.** Toggling packs (API/UI) triggers a scoped re-index; content_hash keeps it incremental.
4. **Budget guard.** `everything` preset can exceed sane injection/index sizes; the picker shows each pack's `approx_bytes` and warns past a threshold.

## First-run UX

During `first_run` / setup, one question after the model step:

> **What will you mostly use Layla for?** — Companion · Maker (CNC/electronics) · Engineer · Researcher · Everything · Customize…

Maps to a preset → writes `knowledge_preset`. "Customize" lists packs with summaries + sizes. Fully skippable (defaults to `companion`).

## API / UI

- `GET /knowledge/packs` → registry + which are enabled + index status per pack.
- `POST /knowledge/packs {enabled:[...]}` → set + trigger scoped re-index.
- Settings → Knowledge: checklist of packs with summaries, sizes, and an index/"ready" chip; a preset dropdown.

## Migration

- Move existing per-aspect + domain docs from `knowledge/` root into the matching pack; leave a short `knowledge/README` note. Loose files remain supported.
- One-time: on upgrade, if `knowledge_preset`/`knowledge_packs` unset, default to `companion` and surface a one-time toast pointing at the new picker.

## Rollout (v1.7.5)

1. Land `knowledge/packs/` + real content (this PR authors the packs).
2. Registry/preset/manifest files + a `test_knowledge_packs.py` (front matter valid, every `docs[]` file exists, sizes recorded).
3. Delivery fixes (injection allow-list + fallback indexing) behind the existing `use_chroma`/fallback plumbing.
4. First-run picker + Settings UI + the two API routes.
5. Docs: update `knowledge/README.md` and this file to "shipped".

Steps 1–2 are content + data (low risk, shippable immediately). Steps 3–5 are the code and can follow within the 1.7.5 cycle.
