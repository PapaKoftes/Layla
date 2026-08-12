---
priority: support
domain: fabrication
aspect: morrigan
summary: Sheet nesting efficiency, grain, kerf/tabs, material behavior, tear-out, vacuum hold-down, part flow.
---

# Nesting & Sheet Goods (Cabinetry)

Nesting = arranging cabinet parts on standard sheets to maximize yield while
respecting grain, tool access, hold-down, and downstream assembly. This is the
bridge between PolyBoard/OptiNest-style layout and the router.

## Nesting efficiency

- **Yield** = used area / sheet area. Good cabinet nests commonly land ~75–90%+
  depending on part mix and grain constraints; grain-locked parts cut yield.
- Drivers of yield: part-size variety (mix big + small to fill gaps), allowing
  rotation (blocked by grain), tight but safe part spacing, and offcut reuse.
- **Common sheet sizes**: 2440×1220 mm (8×4 ft), 3050×1220 mm, plus metric
  2800×2070 panels in Euro cabinetry. Set the real usable area (minus trim edge)
  in the nester.
- Keep a **remnant/offcut library** so the nester reuses drops instead of virgin
  sheets.

## Grain direction

- **Grained materials** (veneer ply, melamine woodgrain, solid wood) must keep
  grain running a consistent direction on show faces — usually **vertical on door/
  gable fronts**, matching within a cabinet. This **forbids 90° rotation** of those
  parts in the nest and lowers yield.
- Non-grain / uniform materials (plain MDF, white melamine, some HDF) rotate
  freely → best yield. Flag grain per material in the library so the nester knows
  which parts can rotate.

## Kerf, spacing, tabs, and offsets

| Setting | What it is | Typical starting point |
|---------|-----------|------------------------|
| Kerf / tool diameter | Router bit cuts a slot of its full diameter; parts must be offset half-kerf | Set = actual bit Ø (e.g. 6 mm). |
| Part-to-part gap | Space between nested parts so adjacent cuts don't merge | ~ tool Ø + small margin (e.g. 8–12 mm for a 6 mm bit). |
| Sheet edge margin | Keep cuts off the clamped/rough sheet edge | ~10–20 mm. |
| Tabs/bridges | Hold parts to the field on through-cut | ~3–6 mm wide, 1–3 mm tall, 1–3 per short part, more on long parts. |
| Onion skin | Thin uncut floor instead of tabs | ~0.2–0.8 mm; needs flat spoilboard. |

**Cut-order matters:** cut inner features (dados, pockets, hinge/drill) **before**
the outer profile, so the part is still fixed to the sheet when you machine its
holes. Cut small interior parts before the large surrounding part releases.

## Material behavior (this changes bit + strategy)

| Material | Behavior | Notes |
|----------|----------|-------|
| Plywood | Layered veneers, alternating grain; top/bottom veneer prone to tear-out and splinter | Compression bit to shear both faces clean; watch voids in cheap ply. |
| MDF | Homogeneous, no grain, very abrasive dust; cuts clean edges | Dulls tools fast (abrasive) → carbide, expect wear; fine dust needs strong extraction (respiratory hazard). |
| Melamine / laminate | Hard brittle resin skin over MDF/particle; chips easily on edges | Compression bit essential; sharp tool, climb finish; scoring pass for bottom face if chipping. |
| Solid wood | Real grain → directional tear-out, movement, knots | Respect grain direction for feed; climb finish; expect movement/cupping, not perfectly flat. |
| Particleboard | Coarse, loose core, moderately abrasive | Similar to MDF; edges weaker, holds screws poorly. |

## Tear-out control

- Use a **compression bit** on double-sided laminated sheets: upcut lower flutes +
  downcut upper flutes shear both faces cleanly (the standard cabinet bit).
- Ensure the **compression transition** (where up meets down) sits *within* the
  material thickness on the first full-depth pass — else one face isn't sheared.
- Downcut bit gives a clean **top** edge (packs chips down — worse evacuation,
  more heat in deep cuts). Upcut gives clean bottom + great evacuation but fuzzy
  top.
- Sharp tools, correct chipload (avoid rubbing), climb finish pass, and a backing
  spoilboard all reduce breakout on the bottom face.
- A light **scoring pass** (shallow first pass along the profile) protects brittle
  melamine bottom edges.

## Spoilboard & vacuum hold-down

- **Spoilboard** (sacrificial MDF layer): protects the table, provides a flat
  datum, and is what your through-cuts cut *into*. **Surface/flatten it** with a
  facing pass so Z0 is truly flat across the whole sheet — critical for onion-skin
  and consistent through-cuts.
- **Vacuum table** pulls the sheet flat and holds it; hold-down force ∝ contact
  area × vacuum level. As parts are cut free they lose their own vacuum area, so:
  keep tabs on small parts, cut small parts first, and don't over-fragment.
- Porous MDF acts as a plenum spreading vacuum through the spoilboard; keep the
  spoilboard sealed on edges and re-face when it stops holding.
- Non-vacuum shops: screw-down through waste areas, clamps at sheet edges, or
  tape-and-glue small parts.

## Labeling & part flow (cabinetry)

- The nester should **label each part** (cabinet ID, part name, edgebanding, hinge/
  hardware, grain arrow) — printed labels or a machine-applied label routine.
- Label **while the part is still in the sheet** (or a print-and-place step) so
  parts don't get orphaned after cut.
- Flow: nest → cut → **label** → sort by cabinet → edgeband → drill/hardware →
  assemble. A consistent part-numbering scheme (cabinet/part) prevents mixing
  identical-looking panels.
- Track offcuts back into the remnant library to raise the *next* job's yield.
