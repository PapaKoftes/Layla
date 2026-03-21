# Fabrication assist layer (knowledge for Layla)

This note is indexed like other curated `knowledge/*.md` files. It describes **how the open-source repo models fabrication assist** so answers stay aligned with code and ethics.

## Roles

1. **Assist (this repo’s `fabrication_assist` package)**  
   Proposes variants, compares stub or real metrics, explains tradeoffs, keeps a **local JSON session** (`history`, `variants`, `outcomes`, `preferences`). It is a **guide and organizer**, not a certificate of manufacturability.

2. **Deterministic kernel (operator-supplied)**  
   Whatever produces authoritative or scored outcomes (your CAM rules, FEA, in-house evaluation engine, external service). Plug it in by implementing **`BuildRunner`** in `fabrication_assist/assist/runner.py`’s contract: `run_build(config: dict) -> dict` with a stable, documented shape (e.g. `variant_id`, `score`, `metrics`, `feasible`, `notes`).

## CLI and exit codes

Operator-facing behavior (flags, exit codes 0–5, `--json` error payloads) is documented in [docs/FABRICATION_ASSIST.md](../docs/FABRICATION_ASSIST.md).

## Code map

| Piece | Path |
|--------|------|
| Orchestration | `fabrication_assist/assist/layla_lite.py` — `assist()`, `parse_intent()` |
| Session I/O | `fabrication_assist/assist/session.py` |
| Variants | `fabrication_assist/assist/variants.py` — `propose_variants()`, `load_knowledge_dir()` |
| Explain | `fabrication_assist/assist/explain.py` |
| Adapter | `fabrication_assist/assist/runner.py` — `BuildRunner`, `StubRunner` |
| Example domain YAML | `fabrication_assist/assist/knowledge/*.example.yaml` |
| Human doc | [docs/FABRICATION_ASSIST.md](../docs/FABRICATION_ASSIST.md) |

## Domain knowledge (generic sources)

Use standard references when reasoning about DFM, tolerances, and process planning (examples: ISO GPS / ASME Y14.5 for tolerancing; machine builder docs for feeds/speeds; material datasheets from mills). **Do not** treat stub scores from `StubRunner` as physical truth.

## Ethics / safety

- Assist output is **decision support**; critical design and safety sign-off remain with the operator and their processes.
- File writes and shell execution elsewhere in Layla remain behind **approval**; this package does not bypass that.

## Related in-repo knowledge

- [morrigan-fabrication-geometry.md](morrigan-fabrication-geometry.md) — fabrication/geometry orientation for the engineering aspect.
