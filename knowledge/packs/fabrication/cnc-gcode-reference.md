---
priority: core
domain: fabrication
aspect: morrigan
summary: G-code/M-code essentials a router/mill operator uses daily, with a worked program and alarm triage.
---

# CNC G-code & M-code Reference (Router/Mill)

G-code is modal: a command stays in effect until changed. Group codes conflict
(you cannot be in G0 and G1 at once). Always know your current *modal state*:
motion mode, units, plane, work offset, absolute/incremental, feed mode.

## Motion (the four you use constantly)

| Code | Meaning | Notes |
|------|---------|-------|
| G0 | Rapid traverse | Positioning only, **never in the cut**. Path may be non-linear/dogleg between axes. |
| G1 | Linear feed | Cutting move at commanded feed `F`. |
| G2 | Clockwise arc | CW as viewed looking down the plane's normal (G17: from +Z). |
| G3 | Counter-clockwise arc | CCW. |

Arc definition: either `R` (radius) or `I/J/K` (center offset from start, signed,
relative to start point in the active plane). I/J/K is unambiguous; `R` has a
short-arc/long-arc sign ambiguity (negative R = arc >180°). Prefer I/J for full
circles (R cannot describe a 360° arc).

## Units, planes, positioning mode

| Code | Meaning |
|------|---------|
| G20 / G21 | Units inch / mm. **Set this explicitly at program top** — wrong units = 25.4× crash. |
| G17 / G18 / G19 | Plane XY / XZ / YZ. Routers ~always G17. Arcs & cutter comp use active plane. |
| G90 / G91 | Absolute / incremental positioning. |
| G94 / G95 | Feed per minute / feed per revolution. Routers use G94 (units/min). |
| G93 | Inverse-time feed (used by some 4/5-axis posts). |

## Work offsets (G54–G59)

G53 = machine coordinates (absolute, from home/machine zero) — used for safe
retracts and tool-change positions. G54–G59 = the six work coordinate systems
(WCS); G54 is the default. G54.1 P__ (or G54 P__) extends to extra offsets on
many controls. The WCS origin is the *part zero* you set (edge/corner/center,
top of stock). Set it with an edge finder, probe, or tool-touch. **Gotcha:** a
program that ran fine "yesterday" will crash if the wrong WCS is active or the
offset was zeroed.

Offset chain (typical): Machine zero → G54 work offset → G43 tool-length offset
(H word) → programmed coordinate. If a Z move is off by exactly the tool length,
suspect a missing/blank `G43 H__` or wrong H number.

## Cutter compensation (basics)

- `G41` = comp **left** of path (climb for CW contour), `G42` = comp **right**,
  `G40` = cancel. Comp uses the diameter/radius in the offset register `D`.
- Purpose: program the *part edge*, let the control offset by tool radius so you
  can tweak fit by editing the offset instead of the program.
- Comp must be **turned on during a linear lead-in move** at least as long as the
  tool radius, and **cancelled on a lead-out**. Turning it on/off inside an arc
  or with a too-short move throws an interference alarm.
- Many wood CAM posts bake comp into the toolpath ("computer comp / in CAM") and
  never emit G41/42 — that's normal and safer for routers. Use control comp only
  when you need on-machine size adjustment.

## Common M-codes

| Code | Function |
|------|----------|
| M0 / M1 | Program stop / optional stop (resume with cycle start). |
| M2 / M30 | Program end / end + rewind. M30 also resets modals. |
| M3 / M4 / M5 | Spindle CW / CCW / stop. Routers almost always M3. |
| M6 | Tool change (with `T__`). Manual-change routers pause here. |
| M8 / M9 | Coolant/mist on / off. On routers often repurposed for vacuum, dust boot, or air blast. |
| M7 | Mist coolant on. |
| M10/M11 | Clamp / unclamp on some machines (or vacuum zones). Check your machine's ladder. |

Router/spindle note: many spindles need a **spin-up dwell**. If M3 S18000 is
followed immediately by a cut, the VFD may still be ramping — add `G4 P2`
(dwell 2 s) or let the post insert one. Also confirm max RPM before commanding S.

## Worked example (mm, simple pocket + profile, CAM-comp style)

```gcode
%
O1001 (SAMPLE POCKET + PROFILE)
G21 G17 G90 G94        ; mm, XY plane, absolute, feed/min
G54                    ; work offset = part zero at top-left corner, Z0 = top of stock
G0 Z15.0               ; safe retract
T1 M6                  ; 6 mm 2-flute compression bit
S18000 M3             ; spindle CW 18000 rpm
G4 P2                  ; dwell for spin-up
G0 X20.0 Y20.0        ; rapid over pocket start
Z5.0                  ; approach height
G1 Z-3.0 F900          ; plunge to 3 mm depth (slower plunge feed)
G1 X60.0 F2500         ; cut pocket sides at feed 2500 mm/min
Y50.0
X20.0
Y20.0
G0 Z15.0               ; retract
G0 X-8.0 Y-8.0         ; move to profile lead-in (outside part)
G1 Z-6.5 F900          ; full-depth profile pass (through 6 mm sheet + 0.5 onion? see CAM)
G1 X108.0 F3000        ; ... contour moves would continue ...
G0 Z15.0
M5                     ; spindle off
G0 G53 Z0              ; retract to machine Z home
M30                    ; end
%
```

`%` frames the program on many controls; `O____` is the program number; `;` or
`( )` are comments. Feeds shown are placeholders — see the feeds-and-speeds doc.

## Reading & interpreting common alarms

Alarms are control-specific (Fanuc/Haas/Mach/GRBL/LinuxCNC differ) but classes
recur. Read the alarm *number and text*, note the line it stopped on.

| Symptom / class | Likely cause | First checks |
|-----------------|--------------|--------------|
| Soft/over-travel limit | Move exceeds machine envelope; wrong WCS or oversized part placement | Verify G54 offset, part position, tool length; jog inside limits, re-home. |
| Cutter comp interference | G41/42 lead-in too short, comp toggled in an arc, inside corner smaller than tool radius | Fix lead-in/out geometry or offset value; or use CAM comp. |
| Unknown / illegal G-code word | Post mismatch, stray character, control lacks that canned cycle | Confirm correct post-processor; open program at cited line. |
| Spindle fault / not at speed | VFD fault, no spin-up dwell, RPM over max | Add dwell, check VFD error, reduce S. |
| E-stop / servo/drive fault | Physical E-stop, drive alarm, lost step (steppers) | Clear E-stop, reset drives, re-home; investigate mechanical bind. |
| GRBL "error: Hard limit" / "ALARM:1" | Limit switch tripped mid-move | Clear alarm ($X), re-home ($H), find why it overshot. |
| GRBL "error:9 / G-code locked out" | Machine in alarm/hold, needs unlock/home | `$X` unlock then `$H`. |
| Feed hold that won't resume | Optional stop M1 active, tool-change wait, or door interlock | Check mode switches, close guard, cycle start. |

**Rule:** after any alarm/crash, do not blindly resume mid-program. Retract to a
safe Z (`G53 Z0`), verify tool length and WCS, and restart from a known safe
block or the operation start.
