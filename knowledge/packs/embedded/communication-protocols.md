---
priority: support
domain: embedded
aspect: morrigan
summary: UART, I2C, SPI, and CAN — when to use, wiring, addresses/pull-ups/modes/CS, speeds, and debugging.
---

# Communication Protocols

Pick the bus by distance, device count, speed, and pin budget. Then wire it right.

## Quick Comparison

| Bus  | Wires (+GND)        | Devices        | Speed (typical)      | Clock | Duplex | Distance |
|------|---------------------|----------------|----------------------|-------|--------|----------|
| UART | 2 (TX, RX)          | 2 (point-point)| 9.6k–115.2k–1M+ baud | none  | full   | short    |
| I2C  | 2 (SDA, SCL)        | many (addr)    | 100k/400k/1M/3.4M    | yes   | half   | short (board) |
| SPI  | 3 + 1 CS/device     | many (CS)      | 1–50+ MHz            | yes   | full   | short    |
| CAN  | 2 (CANH, CANL)      | many (arb)     | 125k–1 Mbps          | none* | half   | long, noisy |

*CAN is asynchronous but bit-timed; nodes sync on edges.

## UART (async serial)

- **Wiring**: TX→RX and RX→TX (crossover), common GND. No shared clock, so both ends
  must agree on **baud, data bits, parity, stop bits** (commonly 8N1).
- Point-to-point (one talker, one listener per direction). For multi-drop use RS-485
  (differential) transceivers.
- **Levels**: MCU UART is TTL (3.3/5 V). "RS-232" from a PC is ±12 V — needs a
  transceiver (MAX232). Match logic levels; level-shift 5↔3.3.
- Uses: debug console, GPS, modules (BT/WiFi), sensor bridges.
- **Debug**: baud mismatch → garbage characters. Wrong crossover → nothing. Check
  common ground. Watch RX buffer overflow at high baud.

## I2C (two-wire, addressed)

- **Wiring**: SDA (data) + SCL (clock), shared by all devices. **Open-drain** lines
  need **pull-up resistors** to the bus voltage (one pair total, not per device).
  ~4.7 kΩ at 100 kHz; ~2.2 kΩ or lower for 400 kHz / long buses. Too weak → slow rise
  → errors; too strong → exceeds sink current.
- **Addresses**: each device has a 7-bit address (8-bit form shifts left + R/W bit).
  Two devices with the same fixed address **conflict** — use address-select pins, a
  different bus, or an I2C mux (TCA9548A). Scan the bus at boot to enumerate.
- **Multi-device**: master addresses one slave at a time; supports clock stretching
  (slave holds SCL low to pause master).
- **Levels**: mixed 3.3/5 V I2C needs a proper bidirectional level shifter; tie
  pull-ups to the correct rail.
- **Debug**: no ACK → wrong address or bad wiring/pull-ups. Bus stuck LOW → a slave
  hung mid-transfer (pulse SCL to recover). Missing pull-ups = the classic dead bus.
  A logic analyzer decoding I2C shows address + ACK/NACK instantly.

## SPI (four-wire, full-duplex)

- **Wiring**: SCLK (clock), MOSI (master→slave), MISO (slave→master), plus **one CS/SS
  (chip select) per device**, active LOW. Devices share SCLK/MOSI/MISO; CS picks who
  listens. Idle (deselected) slaves must tri-state MISO.
- **Modes** (CPOL/CPHA) — must match the slave's datasheet:

  | Mode | CPOL | CPHA | Clock idle | Sample edge |
  |------|------|------|-----------|-------------|
  | 0    | 0    | 0    | low       | rising      |
  | 1    | 0    | 1    | low       | falling     |
  | 2    | 1    | 0    | high      | falling     |
  | 3    | 1    | 1    | high      | rising      |

- Fast, simple, no addressing/ACK — but costs a CS pin per device and no built-in
  error checking.
- Uses: displays, SD cards, high-rate ADC/DAC, flash, radios (nRF24).
- **Debug**: wrong mode → shifted/garbled bytes. Forgetting CS low around a transfer →
  nothing. Two devices driving MISO (bad tri-state) → bus contention. Check clock
  speed vs slave max; check MSB/LSB-first setting.

## CAN (robust multi-node bus)

- Differential pair **CANH/CANL**, needs a CAN **transceiver** (MCU CAN controller
  ≠ transceiver) and **120 Ω termination at both ends** of the bus.
- Message-based with IDs; **arbitration** by ID means no bus master and graceful
  collision handling — lower ID wins. Built-in CRC, ACK, and error counters →
  excellent in electrically noisy, long-run, multi-node systems (vehicles, robots).
- Use when you have many nodes over meters of harness in a noisy environment and need
  reliability. Overkill for two chips on one board (use I2C/SPI there).
- **Debug**: missing/incorrect termination is the #1 failure. Baud mismatch → error
  frames. Use a CAN analyzer; watch TX/RX error counters going bus-off.

## General Debugging Toolkit
- **Logic analyzer** with protocol decoding is the fastest way to see what's on the
  wire (UART/I2C/SPI). Trigger on the CS or start bit.
- **Scope** for signal integrity: rise times (weak I2C pull-ups), ringing, level
  problems the logic analyzer hides.
- Verify **common ground** between every device — the silent killer of all buses.
- Check **levels** (3.3 vs 5 V) and **speed** vs the slowest device's max.
- Start slow (low baud/clock), confirm one device, then add devices and speed.
- Keep bus wires short; twist/route away from motor and PWM noise.
