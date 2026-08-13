---
priority: core
domain: embedded
aspect: morrigan
summary: GPIO, ADC/DAC, PWM, timers/interrupts, logic levels, level shifting, power limits, and reading a datasheet.
---

# Microcontroller Fundamentals

The mental model: an MCU is a CPU + memory + peripherals that turn code into voltage
on pins and voltage on pins into numbers. Everything below is "how a pin behaves."

## GPIO (General-Purpose I/O)

Each pin can be configured as input or output.

**Output modes**
- **Push-pull**: pin actively drives HIGH (to Vcc) or LOW (to GND). Default for most MCUs.
- **Open-drain**: pin can only pull LOW or float (high-Z). Needs an external pull-up.
  Used for shared buses (I2C) and level translation.

**Sink vs source current**
- **Source**: current flows *out* of the pin into the load (pin → load → GND).
- **Sink**: current flows *into* the pin from the load (Vcc → load → pin).
- Many MCUs sink more than they source; some are symmetric. **Check the datasheet**
  for per-pin max and total port/chip max (e.g. AVR ~40 mA absolute max per pin,
  ~20 mA safe; ESP32 ~12 mA typical). Exceeding these degrades or destroys the pin.

**Input modes**
- **Floating / high-Z**: reads noise if nothing is driving it. Never leave a digital
  input floating.
- **Pull-up enabled**: internal resistor (~20–50 kΩ) holds pin HIGH; button to GND
  reads LOW when pressed. Most common pattern.
- **Pull-down**: holds LOW; button to Vcc reads HIGH when pressed.

Rule: every digital input must be driven or biased by a pull resistor.

## Digital vs Analog

- **Digital**: pin is either above V_IH (guaranteed HIGH) or below V_IL (guaranteed
  LOW). The band between is undefined — keep signals out of it.
- **Analog**: continuous voltage, read via ADC, produced via DAC/PWM.

## ADC (Analog-to-Digital Converter)

Converts a voltage into a number relative to a reference V_ref.

    code = (V_in / V_ref) * (2^N - 1)      # N = resolution in bits
    V_in = code * V_ref / (2^N - 1)

- 10-bit → 0–1023, 12-bit → 0–4095.
- **Resolution (LSB size)** = V_ref / 2^N. e.g. 3.3 V, 12-bit → 0.8 mV/step.
- V_ref choices: Vcc (noisy), internal bandgap (stable, fixed), external precision ref.
- **Input impedance**: ADCs need a low-impedance source (sample cap must charge).
  Add a buffer op-amp or small cap for high-impedance sensors.
- Never exceed V_ref / Vcc on the pin. Do not confuse resolution with accuracy —
  noise, INL/DNL, and V_ref drift limit real accuracy.

## DAC / PWM as analog out

- **True DAC**: outputs an actual analog voltage (some MCUs, e.g. ESP32, SAMD).
- **PWM**: a square wave switched fast; average voltage = duty cycle.

      V_avg = duty * V_supply        # duty = t_on / period (0..1)

  Low-pass filter (R + C) to smooth into DC, or use directly for LEDs/motors where
  the load or eye integrates it. Higher PWM frequency → smaller filter, but more
  switching loss. Choose frequency above what the load/human perceives (LEDs >~200 Hz,
  motors often 15–25 kHz to be inaudible).

## Timers and Interrupts

Timers count clock ticks; they generate PWM, measure pulse width, and fire periodic
interrupts without blocking the CPU.

**Interrupts (ISRs)** run asynchronously when an event fires (pin change, timer
overflow, UART byte). ISR discipline:

**DO**
- Keep it short — set a `volatile` flag or push to a buffer, handle in main loop.
- Mark shared variables `volatile`.
- Guard multi-byte shared reads/writes against tearing (disable interrupts briefly).

**DON'T**
- No `delay()`, no blocking, no long loops.
- Avoid `Serial.print`, `malloc`, floating point in ISRs where the platform is slow.
- Don't call functions that themselves depend on interrupts (e.g. `millis()` won't
  advance if interrupts are disabled).

## Voltage Levels: 3.3 V vs 5 V Logic

- 5 V parts (classic AVR/Uno) vs 3.3 V parts (ESP32, STM32, most modern MCUs, most
  sensors). Mixing them is the #1 source of "it works but flaky" or dead pins.
- A 3.3 V output *may* register as HIGH on a 5 V input (check V_IH ≈ 0.6·Vcc = 3.0 V —
  marginal), but a **5 V output into a 3.3 V input can destroy it** unless the pin is
  5 V-tolerant (datasheet says so explicitly).

**Level shifting**
- **Simple input-only step-down**: resistor divider (e.g. 5 V→3.3 V with ratio
  ~1.8k/3.3k). Fine for slow signals, not for fast bidirectional buses.
- **Bidirectional / I2C**: dedicated MOSFET level shifter (e.g. BSS138-based board).
- **Unidirectional fast**: logic-level translator IC or level-shifter buffer.
- **Open-drain trick**: on I2C, pull-ups can go to the lower rail if all devices are
  open-drain and tolerant.

## Power and Current

- The MCU's regulator has limits; total current for the MCU **plus** everything it
  powers must stay within source/board limits.
- Don't power motors/servos/relays from the MCU's 3.3 V/5 V pin — use a separate
  supply, share GND. Inrush and stall currents dwarf logic budgets.
- Add decoupling caps (0.1 µF per Vcc pin, plus bulk 10–100 µF near loads).
- Watch brown-out: sagging Vcc resets or corrupts the MCU. Enable brown-out detection.

## How to Reason About a Datasheet

Read in this order:
1. **Absolute Maximum Ratings** — never exceed; these are damage thresholds, not
   operating points.
2. **Recommended Operating Conditions** — the real envelope (Vcc range, temp, clock).
3. **DC Characteristics** — V_IH/V_IL (logic thresholds), V_OH/V_OL, I_OH/I_OL
   (drive strength), pull-up values, leakage.
4. **AC / Timing** — setup/hold, max clock, rise/fall, bus timing diagrams.
5. **Pinout + Alternate Functions** — which peripherals map to which pins.
6. **Application / Typical Circuits** — decoupling, reference wiring.

When unsure of a number, **look it up in the datasheet** rather than guessing —
part variants differ and absolute-max violations are silent killers.

## Quick Checklist
- [ ] Inputs never floating (pull-up/down set)?
- [ ] Per-pin and total current within datasheet limits?
- [ ] Logic levels matched or shifted?
- [ ] V_ref correct and pin voltage ≤ V_ref for ADC?
- [ ] ISRs short, shared vars `volatile`?
- [ ] Decoupling caps present; loads on separate supply with common GND?
