---
priority: support
domain: fabrication
aspect: morrigan
summary: Workholding methods, avoiding hold-down collisions, dust/chip management, and machine safety rules.
---

# Workholding & Safety

Workholding must beat the cutting force in every direction (lift, drag, spin)
without putting a clamp where the tool will go. Most catastrophic router failures
are a part coming loose or the tool hitting a fixture.

## Workholding methods

| Method | Best for | Watch out |
|--------|---------|-----------|
| **Mechanical clamps / toe clamps** | Solid stock, thick parts, edge holding | Keep clamp bodies **out of every toolpath and rapid**; clamp low so tool/holder clears. |
| **Vacuum table / pods** | Full sheets, flat panels, production | Loses grip as parts cut free & lose area; needs flat sealed spoilboard; not for tiny/porous parts alone. |
| **Screws through waste** | Sheet goods on a spoilboard | Only into waste/tab areas; know screw locations so you never cut one (tool + eyes hazard). |
| **Tape-and-glue** (painter's tape + CA glue) | Small parts, no-vacuum shops, thin stock | Surface must be clean; test hold; residue on show face. |
| **Fixtures / jigs** | Repeat parts, odd shapes, second-op | Must be shorter than clearance plane or explicitly avoided in CAM. |
| **T-track / cam clamps** | Flexible edge clamping | Same rule: clear of cutter and rapids. |

## Avoiding cutting into hold-downs (the #1 crash)

- **Model the fixture/clamps and screws in CAM**, or at minimum mark keep-out
  zones; verify no toolpath or **G0 rapid** crosses them.
- Set the **rapid/clearance plane above the tallest clamp/fixture.** Many crashes
  are a rapid at low Z clipping a clamp, not the cut itself.
- Place screws/tabs only in waste; keep a map of screw positions before you cut.
- Set **Z0 deliberately** (spoilboard top vs material top) so through-cuts cut
  into the spoilboard, not the table — and don't over-cut into T-slots/aluminum
  bed.
- Simulate with the fixture visible; check the **tool holder/collet**, not just
  the tip, for collisions on deep cuts.
- Confirm the physical setup matches the CAM stock/fixture placement before cycle
  start.

## Dust & chip management

- **Fine wood/MDF dust is a respiratory hazard and can be explosive** in high
  concentration — extraction is safety gear, not just cleanliness.
- Run a **dust shoe/boot** at the spindle tied to a collector/vacuum with enough
  CFM; keep the brush skirt near the surface.
- MDF/composite dust especially: good filtration (fine particulate), empty/clean
  filters, and wear a **respirator** rated for fine dust when extraction is
  imperfect.
- Keep chips clear of the cut — recutting chips dulls tools and (in aluminum)
  welds to the flute. Air blast/mist helps in metal/plastic.
- **Fire/static:** dust in ducting plus a spark or hot chip is an ignition risk;
  don't let bits burn (dull-tool scorching), keep the machine and collector clean.

## Machine safety rules

- **Eye protection always;** hearing protection for routers; respirator for fine
  dust. No loose clothing, gloves, jewelry, or long hair near the spindle — a
  rotating tool grabs and pulls.
- **Know your E-stop and feed-hold** before starting; keep a hand ready on the
  first cut of any new program.
- **Spindle stopped, and powered down/locked, for tool changes**, collet cleaning,
  and reaching into the envelope. Never touch a coasting spindle.
- **Never reach toward a spinning tool** to clear chips or feel the cut — stop the
  spindle first.
- **Prove out new programs:** simulate, then an **air cut / dry run above the
  stock** (or Z raised) before cutting material; watch rapids and retracts.
- Verify **RPM ≤ tool and spindle max**, correct WCS/offsets, correct tool
  numbers/lengths, and workholding secure before cycle start.
- **Keep the work area clear**; don't leave tools/clamps on the table; secure the
  sheet before homing/rapids.
- Stay at the machine while it runs; don't leave a cutting router unattended.
  Ventilate and manage dust; keep a fire extinguisher (dust/electrical rated)
  nearby.
- After a **crash or alarm**: stop, don't blindly resume — retract to safe Z,
  re-verify tool length, WCS, and workholding, inspect the tool, then restart from
  a known-safe block.

## Quick pre-cut safety checklist

1. PPE on (eyes, ears, dust); loose items secured.
2. Workholding secure; clamps/screws mapped and clear of all paths + rapids.
3. Right tool, right length, collet clean & correct size, tool tight.
4. Correct WCS/offset; Z0 set to intended datum; RPM within limits.
5. Program simulated; clearance plane above fixtures; dry/air run done.
6. Dust extraction on; area clear; E-stop within reach; you're staying put.
