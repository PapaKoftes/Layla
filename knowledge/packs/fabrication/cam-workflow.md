---
priority: support
domain: fabrication
aspect: morrigan
summary: Model to machine — stock/WCS, 2D/3D toolpaths, tabs, leads, climb vs conventional, sim, posts.
---

# CAM Workflow: Model → CAM → Post → Machine

The pipeline: **CAD model → set stock & WCS → choose/parameterize toolpaths →
simulate/verify → post-process to G-code → run on machine.** Errors caught in
simulation cost seconds; errors caught on the machine cost tools, parts, or fingers.

## 1. Stock & WCS setup

- **Stock**: define the raw material bounds (sheet size + thickness, or a billet).
  Add extra stock on top if your surface isn't flat; a facing/skim pass squares it.
- **WCS / part zero**: pick an origin you can physically reproduce on the machine.
  - Routers/sheet goods: usually a **corner of the sheet**, **Z0 = top of
    spoilboard** (through-cuts) or **Z0 = top of material** (pockets/engraving).
    Decide deliberately — mixing the two is a classic depth error.
  - Set X/Y/Z origin in CAM to match how you'll touch off on the machine
    (edge finder/probe/tool touch). If CAM says corner + top, touch off corner + top.
- Confirm **model units** match CAM and post (mm vs inch).

## 2. 2D vs 3D toolpaths

**2D / 2.5D** — flat-bottom operations at constant Z levels; the workhorse for
cabinetry and sheet goods.

| Toolpath | Use |
|----------|-----|
| Profile / Contour | Cut around a part outline (inside=slot/pocket edge, outside=part, on-line=engrave). Side comp matters. |
| Pocket / Clearing | Remove material inside a boundary (dados, recesses, hardware pockets). |
| Drill / Bore | Point holes: peck (G83), spot, ream. Helical-bore large holes with an endmill instead. |
| Engrave / Trace | Follow a line at depth (V-carve uses V-bit + varying depth for varying width). |
| Adaptive / Trochoidal clearing | High-material-removal 2.5D clearing keeping constant tool engagement — low radial load, deep axial cuts. Great for hardwood/metal, saves tools. |

**3D** — for contoured/sculpted surfaces (raised panels, reliefs, molds).

| Toolpath | Use |
|----------|-----|
| Roughing (3D adaptive/pocket) | Bulk removal in Z steps leaving stock-to-leave. |
| Parallel / Raster | Finish along parallel lines; good on shallow slopes, poor on vertical walls. |
| Scallop / Constant-stepover | Even finish independent of slope. |
| Contour / Waterline (Z-level) | Finish steep walls at constant Z steps. |
| Pencil | Cleans up internal corners/valleys a bigger tool missed. |

Combine: adaptive rough → rest-rough → finish. Use ballnose for 3D finish;
stepover controls the scallop height (smaller = smoother + slower).

## 3. Tabs / onion-skin (hold the part on through-cuts)

When a profile cuts fully through, the part can shift, lift into the spindle, or
fling. Two strategies:

- **Tabs (bridges):** leave small uncut connectors (e.g. ~3–6 mm wide × ~1–3 mm
  tall for sheet stock) at intervals; snap/trim after. Place tabs on straight
  edges, not corners; avoid tabbing across visible faces.
- **Onion skin:** cut to leave a thin floor (~0.2–0.8 mm) across the whole part,
  then a final light pass or sanding releases it. Better surface than tabs but
  needs a flat spoilboard and reliable Z.
- Vacuum tables may allow tabless cutting if hold-down beats cutting force — but
  keep at least a couple of tabs on small parts that lose vacuum area as they cut.

## 4. Lead-in / lead-out

- Use a **linear or arc lead** to ease the tool into the cut instead of a full-
  depth plunge at the edge — reduces witness marks, tool shock, and (with cutter
  comp) is *required* to establish comp.
- Ramp or helical entry for pockets/plunge-sensitive tools; straight plunge only
  with center-cutting/plunge-rated bits and conservative feed.
- Arc lead-in/out gives the cleanest wall on visible profiles.

## 5. Climb vs conventional (and when each)

Defined by cutter rotation vs feed direction:

- **Climb milling:** chip starts thick, ends thin; cutter pushes with the feed.
  Better surface finish, less tool wear/heat, less tear-out in wood — **default
  for CNC routers and rigid mills**. Needs a rigid machine with no backlash
  (climb tends to pull into the work; loose ballscrews → chatter/grab).
- **Conventional milling:** chip starts thin, ends thick; cutter opposes feed.
  Safer on loose/manual machines, tolerates backlash, better on hard-skinned or
  abrasive stock. Can cause more tear-out/burnishing in wood.
- Practical rule (wood): **climb for finish passes and outside profiles** (clean
  edge), consider conventional or a light climb finish to manage tear-out on
  grain. For a two-pass profile: rough conventional-ish, finish with a light
  climb spring pass. Most sheet-goods CAM defaults to climb for the finish wall.

## 6. Simulation / verification (do not skip)

- **Backplot/toolpath review:** rapids (G0) shouldn't cross the part; check
  retract heights and lead moves.
- **Material/stock simulation:** watch for gouges, uncut regions, collisions with
  clamps/fixtures, and the tool **holder/collet** hitting stock (holder collision
  on deep 3D work).
- Verify **rapid clearance plane** is above every clamp and the tallest fixture.
- Check estimated cycle time and that the last op retracts to a safe machine Z.

## 7. Post-processors

- The **post** translates CAM's neutral toolpath into the exact dialect your
  control accepts (Fanuc, Haas, Mach3/4, GRBL, LinuxCNC, Centroid, etc.).
- **Match the post to the control.** Wrong post = illegal-word alarms, arcs in
  the wrong plane, missing tool-change logic, or bad spin-up.
- Posts encode: units, arc style (R vs IJK), tool-change behavior (auto vs manual
  M6 pause), spindle spin-up dwell, coordinate/retract conventions, and safety
  blocks. Keep a **known-good post per machine** and change it deliberately.
- After any post change, run one part in air / with simulation before cutting.

## Pre-run checklist

1. Right file, right post, right machine.
2. Units correct (G20/G21) and WCS matches physical touch-off.
3. Tool list matches what's in the machine (numbers, diameters, lengths).
4. Stock size/position matches reality; clamps clear of all toolpaths + rapids.
5. Tabs/onion-skin present on through-cuts.
6. Simulated with no gouges/collisions; safe retract at end.
7. First plunge and first feed dialed conservative; hand on feed-hold/E-stop.
