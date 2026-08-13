---
priority: support
domain: fabrication
aspect: morrigan
summary: Chipload-driven feeds & speeds — formulas, SFM→RPM, ap/ae, deflection, chip thinning, starting ranges.
---

# Feeds & Speeds: The Real Method

Feeds and speeds are **derived from chipload, not guessed**. The goal: each flute
takes a proper bite so the chip carries heat away. Too small a chipload =
rubbing/burning/heat/dull tools; too large = deflection, chatter, broken tools.

## Core formula (feed rate)

```
Feed (units/min) = RPM × number_of_flutes × chipload_per_tooth
```

- `chipload` (a.k.a. feed-per-tooth, IPT/mm-per-tooth) is the fundamental number.
- Rearranged to find chipload from a known-good feed:
  `chipload = Feed / (RPM × flutes)`.
- Plunge feed is usually **30–60% of the cutting feed** unless the tool is fully
  plunge-rated (ramp/helix entry preferred).

## Spindle speed from cutting speed (SFM / surface speed)

RPM isn't the target — **surface speed** is (how fast the edge moves through
material). Convert:

```
inch:  RPM = (SFM × 12) / (π × D_inch)      ≈ (3.82 × SFM) / D_inch
metric: RPM = (Vc_m/min × 1000) / (π × D_mm)
```

- SFM/Vc is material- and tool-material-dependent (carbide runs faster than HSS).
- Wood/plastic often run at the router/spindle's **max RPM** anyway, so in
  practice you fix RPM (near max) and solve feed from chipload. Metals: pick SFM
  first, compute RPM, then feed.

## Depth & width of cut (ap / ae)

- **ap = axial depth of cut** (how deep in Z per pass).
- **ae = radial width of cut / stepover** (how much of the tool's diameter engages
  sideways).
- Rules of thumb (starting points, tune per machine rigidity):
  - Slotting (full-width, ae = 1×D): most demanding — reduce feed/ap, clear chips.
  - General wood profiling: ap up to ~1–2× D in one pass on soft sheet with a
    rigid spindle; deeper needs multiple passes or adaptive.
  - **Adaptive/trochoidal**: small ae (~5–15% D) lets you run large ap (1–3× D)
    at constant engagement — more material removed with less load. Preferred for
    hardwood and metal.
- More flutes = more chip volume but less chip clearance; wood/aluminum favor
  **fewer flutes (1–2)** for gullet room; steel/finish favor more (3–4+).

## Tool deflection

Long, thin tools bend under cutting force → oversize cuts, tapered walls,
chatter, breakage. Deflection scales roughly with **stickout³** and inversely
with **diameter⁴** — small changes matter a lot.

- Use the **shortest stickout** and **largest diameter** the job allows.
- Reduce ae (radial engagement) before reducing feed to cut deflection.
- Symptoms: bellmouthed/tapered walls, dimension drift, "singing"/chatter, poor
  finish on one side of a slot.

## Chip thinning (why light stepovers need MORE feed)

When **ae < D/2** (radial engagement under half diameter, e.g. finish passes and
adaptive), the actual chip is thinner than the commanded chipload because the arc
of engagement is short. To keep the true chip at target, you must **increase the
programmed feed** (radial chip-thinning factor). Practically: with light-stepover
or adaptive paths, bump feed up — running "book" feed at 8% stepover will rub and
overheat the edge. Ballnose tools also thin the chip near the tip (effective
diameter shrinks at shallow depth) — increase feed and/or use effective-diameter
RPM.

## Typical STARTING chiploads (tune by sound & chips — NOT gospel)

These are ballpark starting points for a ~6 mm (1/4") tool; **scale up for larger
tools, down for smaller**, and always adjust to your machine, holder, and stock.
Values vary widely by source — treat as a place to begin one test cut.

| Material | Tool type | Starting chipload (per tooth) |
|----------|-----------|-------------------------------|
| Softwood / plywood | Upcut/compression carbide | ~0.10–0.30 mm (0.004–0.012") |
| Hardwood | Compression/upcut carbide | ~0.08–0.20 mm (0.003–0.008") |
| MDF | Up/down/compression carbide | ~0.10–0.30 mm (0.004–0.012") |
| Melamine/laminate | Compression carbide | ~0.05–0.15 mm (0.002–0.006") |
| Acrylic/plastics | O-flute (1-flute) | ~0.10–0.25 mm (0.004–0.010") |
| Soft aluminum | 2–3 flute carbide, single-flute for small D | ~0.02–0.08 mm (0.001–0.003"), needs lube/air & lower SFM handling |

Smaller tools take proportionally smaller chiploads (a 3 mm bit ≈ half of a 6 mm).
For metals also pick SFM (carbide in aluminum runs high; keep it cool, evacuate
chips, avoid recutting).

## Tuning loop (the part that actually matters)

1. Fix RPM (near spindle max for wood/plastic; from SFM for metal).
2. Pick a starting chipload from the table → compute feed.
3. Choose conservative ap/ae; run one test cut.
4. **Read the results:**
   - **Chips**: want dry, formed chips — not fine dust (too slow/rubbing =
     burning) and not oversized packed chips (too aggressive).
   - **Sound**: steady hum good; screeching/chatter = reduce ae or feed, shorten
     stickout, or change RPM to dodge a resonance.
   - **Smell/color**: scorching or brown edges in wood = feed too low or RPM too
     high (rubbing) → **increase feed** or drop RPM.
   - **Finish/edges**: fuzz/tear-out → wrong bit geometry or climb/conventional
     choice; burr in aluminum → dull tool or no chip evacuation.
5. Adjust one variable at a time. Increase feed first to kill burning; reduce ae
   first to kill chatter/deflection.

**Safety:** never reach toward a spinning tool to feel chips; stop the spindle.
Confirm commanded RPM ≤ tool and spindle max before running.
