---
priority: support
domain: embedded
aspect: morrigan
summary: Non-blocking millis() code, debouncing, state machines, serial debug, memory limits, String/watchdog footguns.
---

# Arduino Patterns

Idioms that separate a sketch that "works on the bench" from firmware that runs
for weeks. Applies to AVR (Uno/Nano), but concepts carry to ESP32/STM32.

## Non-Blocking Timing: millis() vs delay()

`delay(ms)` halts everything — no sensor reads, no comms, no other tasks. Use it only
in throwaway demos. Real code compares timestamps.

    // Blink without blocking
    unsigned long prev = 0;
    const unsigned long interval = 500;
    void loop() {
      unsigned long now = millis();
      if (now - prev >= interval) {
        prev = now;              // record, don't accumulate drift
        toggleLed();
      }
      // ... other tasks run every loop ...
    }

- Always compute `now - prev >= interval`. This subtraction is **rollover-safe** with
  `unsigned long` (millis wraps ~49.7 days). Never compare `now >= prev + interval`.
- Keep `loop()` fast; nothing should block longer than your shortest deadline.
- For microsecond timing use `micros()` (wraps ~71 min, coarser resolution ~4 µs).

## Debouncing

Mechanical switches bounce for ~1–20 ms, producing spurious edges.

    // Time-based debounce
    if (reading != lastReading) lastChange = millis();
    if (millis() - lastChange > 25) {   // stable for 25 ms
      if (reading != stableState) { stableState = reading; /* act on edge */ }
    }
    lastReading = reading;

Alternatives: hardware RC filter + Schmitt input, or integrate/count samples.
Debounce in firmware unless you need ISR-clean edges.

## Finite State Machines

Replace tangled flags with an explicit state variable. Readable, testable, non-blocking.

    enum State { IDLE, ARMED, RUNNING, FAULT };
    State state = IDLE;
    void loop() {
      switch (state) {
        case IDLE:    if (startPressed()) state = ARMED;   break;
        case ARMED:   if (sensorReady()) state = RUNNING;  break;
        case RUNNING: if (done()) state = IDLE;
                      if (overTemp()) state = FAULT;       break;
        case FAULT:   holdOutputsSafe();                   break;
      }
    }

Each `case` does a little work and returns to `loop()`. Combine with millis() for
timed transitions.

## Serial Debugging

- `Serial.begin(115200);` — match the baud in the monitor exactly or you get garbage.
- Print sparingly in hot loops; `Serial.print` is slow and blocks until the TX buffer
  drains (or drops data). Throttle with millis().
- Use `F()` macro to keep literals in flash: `Serial.println(F("boot ok"));` — saves
  precious SRAM.
- Toggle a debug pin + logic analyzer for timing you can't see over serial.

## Memory Constraints (know your three memories)

| Memory | Typical (Uno) | Holds | Notes |
|--------|--------------|-------|-------|
| Flash  | 32 KB | program + `F()` literals + PROGMEM tables | non-volatile |
| SRAM   | 2 KB  | variables, stack, heap | **the scarce one** |
| EEPROM | 1 KB  | config/persistent data | ~100k write cycles |

- SRAM exhaustion = silent corruption: stack collides with heap, random crashes.
- Store constant strings/tables in flash with `PROGMEM` / `F()`.
- Prefer fixed-size buffers over dynamic allocation. `sizeof` your structs.
- EEPROM: wear-level (rotate addresses) and never write in a tight loop.

## Avoid String Fragmentation

The `String` class heap-allocates and reallocates; on 2 KB SRAM this **fragments the
heap** and eventually crashes.

- Prefer `char` arrays + `snprintf`, `strcpy`, `strcat`.
- If you must use `String`, avoid concatenation in loops and `reserve()` capacity up
  front.
- Parse serial into a fixed `char buf[N]` with an index, not `String +=`.

## Watchdog Timer

A hardware timer that resets the MCU if firmware hangs.

    #include <avr/wdt.h>
    wdt_enable(WDTO_2S);     // reset if not fed within 2 s
    // ... in loop: wdt_reset();

- Feed it in the main loop, **not** in an ISR (that would mask a real hang).
- Set the timeout longer than your slowest legitimate loop pass.
- On boot, clear reset flags so you know if a WDT reset happened (log it).

## Common Footguns
- `delay()` inside a library call or ISR stalling everything else.
- Missing `volatile` on ISR-shared variables → optimizer caches stale value.
- `int` overflow on AVR (`int` is 16-bit → max 32767); use `long`/`int32_t`.
- Floating point on AVR is software-emulated and slow — avoid in hot paths.
- Powering servos/LEDs strips off the 5 V pin → brown-out resets.
- Forgetting common ground between boards → floating references, nonsense readings.
- `pinMode` forgotten → input floats or output never drives.
- Comparing `==` on floats; comparing millis with signed math.
- Blocking `while(!Serial);` on a board without native USB → hangs forever headless.
