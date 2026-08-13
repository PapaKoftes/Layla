---
priority: support
domain: embedded
aspect: morrigan
summary: Systematic bring-up (power→clock→blink→serial→peripheral), meters/analyzers/scopes, noise, brown-outs, HW vs FW.
---

# Debugging Embedded Systems

The core discipline: **change one thing, measure, don't assume.** Bring a board up in
layers so a failure at layer N means layers 1..N−1 already work.

## Systematic Bring-Up Ladder

Work bottom-up; don't chase a peripheral bug before power is proven.

1. **Power** — measure the actual rail voltage at the chip's Vcc pins (not at the
   regulator input). 3.3/5 V within tolerance? Ripple low? GND continuous? Correct
   polarity? A wrong or sagging rail masquerades as every other bug.
2. **Clock** — is the MCU running? Crystal oscillating (scope), or internal oscillator
   fuse/config correct? No clock → nothing runs. On AVR check fuses; on STM32/ESP check
   clock config.
3. **Blink** — the "hello world." A bare LED toggle proves power + clock + core +
   toolchain + flashing all work. If blink fails, the problem is upstream of your app.
4. **Serial** — bring up UART and print. Now you have eyes: boot banner, reset cause,
   variable dumps. Verify baud matches the monitor.
5. **Peripheral** — add one bus/sensor/actuator at a time. Confirm each before the
   next. Enumerate I2C (scan), read a known register, verify against datasheet.

If something breaks, drop back down the ladder until it works, then climb again.

## Instruments and What They See

| Tool | Best for | Limits |
|------|----------|--------|
| **Multimeter (DMM)** | DC voltage, continuity, resistance, current (in series), shorts | too slow for signals; averages |
| **Logic analyzer** | digital timing, decoding UART/I2C/SPI, "is the bus doing anything?" | only HIGH/LOW, hides analog problems |
| **Oscilloscope** | analog waveforms, rise/fall, ringing, noise, glitches, PWM shape | steeper learning curve, fewer channels |

- **Continuity/short check first** with a DMM before powering a new board — catch Vcc↔GND
  shorts before smoke.
- Measure **current** by breaking the circuit and putting the DMM in series; a spike
  above expected = short/stall.
- **Logic analyzer** answers "is data on the wire and is it correct?" — decode the
  protocol and read address/ACK/bytes directly.
- **Scope** answers "why is the correct-looking signal failing?" — slow I2C edges from
  weak pull-ups, brown-out dips, reflections, noise coupling.

## Grounding and Noise

- **Common ground** between every board/module/supply — the most common wiring fault.
  Different grounds → floating references → random readings and comms failures.
- **Star ground / separate returns**: keep high-current motor return away from sensitive
  analog/logic ground; join at one point.
- **Decoupling**: 0.1 µF at every Vcc pin + bulk 10–100 µF near loads. Missing decoupling
  = intermittent resets and ADC noise.
- Keep motor/PWM wiring twisted and away from signal lines; add snubber/caps across
  brushed motors. Shield or route analog sensors carefully.
- Ground loops and long unshielded ADC leads pick up 50/60 Hz and switching noise —
  filter and shorten.

## Brown-Outs and Resets

- **Brown-out**: Vcc dips below the MCU's minimum (often when a motor/servo/relay draws
  current), causing resets or corrupted state. Symptoms: board resets when a load
  engages, garbage on serial, EEPROM corruption.
- Fixes: separate/beefier supply for loads, bulk capacitance, enable brown-out
  detection (BOD) so it resets cleanly instead of running corrupted.
- Log the **reset cause** at boot (power-on, brown-out, watchdog, external). Knowing
  *why* it reset narrows the hunt fast.
- A watchdog reset loop usually means firmware hangs; a brown-out loop means power.

## Isolating Hardware vs Firmware

Bisect the boundary deliberately:

- **Minimal reproducer**: strip the sketch to just the failing peripheral. If it works
  alone, something else (timing, memory, shared bus) is the cause.
- **Swap one variable**: another identical sensor/cable/board — does the fault follow
  the part (hardware) or stay (firmware/wiring)?
- **Measure the wire**: if the MCU says it sent the right bytes but the analyzer shows
  garbage → hardware/levels/wiring. If the wire is clean but behavior is wrong →
  firmware logic.
- **Known-good reference**: flash a vendor example; if that works, your code differs.
- **Check the obvious first**: floating inputs, missing pull-ups, wrong pin, TX/RX not
  crossed, level mismatch (5 V into 3.3 V), no common ground, insufficient current.
- **Firmware-side smells**: missing `volatile`, stack/heap collision (SRAM out — see
  arduino-patterns), integer overflow, blocking `delay()` starving other tasks,
  uninitialized peripheral registers.

## Fast Triage Checklist
- [ ] Rail voltage correct at the chip, low ripple, common ground?
- [ ] Does a bare blink run? (isolates power/clock/toolchain)
- [ ] Serial boot banner + reset cause printed?
- [ ] Continuity/short check done before power?
- [ ] Pull-ups/termination present (I2C/CAN)? Levels matched?
- [ ] Loads on separate supply; decoupling caps in place?
- [ ] Fault follows the part (hardware) or the code (firmware)?
- [ ] Signal on the wire verified with analyzer/scope, not assumed?
