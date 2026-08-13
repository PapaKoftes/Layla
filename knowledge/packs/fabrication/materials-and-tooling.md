---
priority: support
domain: fabrication
aspect: morrigan
summary: Router bit geometries, coatings, when to use each, material notes, wear signs, collet care.
---

# Materials & Tooling (Router Bits)

The bit geometry decides edge quality, chip evacuation, and which face tears out.
Pick geometry first, then flutes/coating.

## Bit types by flute geometry

| Type | Flute direction / shape | Clean edge on | Chip evacuation | Use when |
|------|------------------------|---------------|-----------------|----------|
| **Upcut** (up-spiral) | Pulls chips **up/out** | Bottom face | Excellent | Pockets, deep cuts, chip-clearing priority; slotting where top fuzz is OK. |
| **Downcut** (down-spiral) | Pushes chips **down** | Top face | Poor (packs chips) | Clean top surface, holds veneer/laminate down; shallow cuts, no vacuum. Watch heat/burn in deep cuts. |
| **Compression** | Up-spiral bottom + down-spiral top | **Both faces** | Good | Double-laminated sheet goods (ply, melamine) — the cabinet standard. Needs transition inside material. |
| **Straight** | Straight flutes | Neutral | Fair | General trimming, plunge, some hand-router work; simpler, cheaper, less shearing. |
| **Ballnose** | Rounded tip | 3D surfaces | Good | 3D finishing/contours (raised panels, reliefs); scallop set by stepover. |
| **V-bit** | Included angle (e.g. 60°/90°) | Line-following | — | V-carving lettering/signs; width varies with depth. |
| **O-flute** (single) | One flute, polished gullet | Plastics | Excellent | Acrylic/plastics — big gullet clears molten chips, prevents re-welding. |

**Flute count:** fewer flutes (1–2) = bigger gullets, better chip clearance for
wood/plastic/aluminum; more flutes (3–4+) = smoother finish and higher feed in
harder/denser material but clog in wood.

## Coatings

| Coating | Helps with | Notes |
|---------|-----------|-------|
| Uncoated carbide | General wood/plastic | Fine for most sheet goods. |
| TiN (titanium nitride) | General purpose, mild hardness/lubricity | Gold color; modest life boost. |
| TiCN / AlTiN / TiAlN | Harder/hotter cutting, some metals | AlTiN likes high heat (metal). |
| ZrN | Aluminum & non-ferrous | Low built-up-edge tendency. |
| Diamond / DLC / PCD | **Abrasive** MDF, laminate, composites, CFRP | PCD tools cost more but last many times longer in MDF/laminate — worth it in production. |

For **MDF/laminate production**, abrasion is the killer — a diamond/PCD or at
least a good carbide with a wear-resistant coating pays back. For **aluminum**,
use ZrN/uncoated sharp carbide, **avoid TiN-on-aluminum galling**, run fewer
flutes, and provide lubricant/air to clear chips (aluminum welds to the flute if
recut).

## Material notes

- **MDF/particleboard:** highly abrasive → expect fast wear; carbide/diamond,
  strong dust extraction (fine dust is a respiratory + fire hazard).
- **Laminate/melamine:** brittle skin → compression bit, sharp edge, climb finish,
  optional scoring pass; dull tools chip the edge.
- **Aluminum (non-ferrous):** single/2-flute, chip evacuation + lube/air,
  moderate SFM, avoid recutting chips; watch for built-up edge and gummy chips.
  It is a metal — heat, sharp swarf, and tool grabbing are real hazards.
- **Plastics:** O-flute, avoid melting (feed enough to make chips, not dust);
  acrylic chips can re-weld if RPM too high / feed too low.

## Tool wear signs (replace/resharpen before it costs a part)

- **Burning/scorching** on wood edges, or brown dust → dull edge rubbing (also
  check feed too low / RPM too high).
- **Increased fuzz / tear-out** that a fresh bit didn't leave.
- **Rising cutting sound/pitch, more vibration or chatter** at the same settings.
- **Rounded/chipped cutting edge** visible under magnification; loss of the sharp
  corner radius.
- **Oversize or tapered cuts** (deflection from a worn/dull tool pushing harder).
- **More power draw / spindle load** for the same cut.
- Track tool life; in abrasive MDF a bit can go dull within a sheet or two.

## Collet & tool-holding care (accuracy + safety)

- The **collet grips the shank**; a worn/dirty collet = runout, pull-out, poor
  finish, and broken tools. Treat it as a precision part.
- **Clean** collet and nut regularly (bristle brush/solvent); remove dust and
  resin. Never leave chips in the taper.
- **Do not bottom the tool** against the collet base; insert shank fully into the
  collet grip length but leave a small gap; grip on the shank, never on the
  flutes.
- Use the **right collet size** for the shank — never squeeze an undersized shank;
  a reducer/adapter is not a substitute for the correct collet.
- Tighten to spec (collet nut seats the collet into the taper); replace collets
  that show bell-mouthing, cracks, or scoring — they lose grip and add runout.
- Check **runout** (TIR) periodically; excess runout ruins finish and shortens
  tool life. Suspect the collet/nut/taper before blaming the tool.
- **Safety:** spindle stopped and powered/locked before changing tools; carbide
  edges are razor-sharp and chip — handle by the shank, wear eye protection, and
  keep fingers clear of the flutes.
