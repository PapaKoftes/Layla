---
priority: support
domain: embedded
aspect: morrigan
summary: Reading pots/temp/ToF/IMU/encoders, driving LEDs/relays/servos/steppers/motors, MOSFETs, flyback diodes, filtering.
---

# Sensors and Actuators

How to get clean numbers *in* and drive real loads *out* without frying pins.

## Reading Sensors

### Analog potentiometer / voltage sensors
- Wire pot: ends to Vcc and GND, wiper to ADC pin. Reads 0..(2^N−1) across travel.
- Scale: `value = analogRead(pin) * range / (2^N - 1)`.
- High-impedance sources need a buffer or small cap so the ADC sample cap settles.

### Temperature
- **Thermistor (NTC)**: voltage divider with a fixed resistor; convert with the
  Steinhart-Hart or Beta equation. Non-linear — **check the datasheet** for Beta/R25.
- **Analog IC (e.g. LM35/TMP36)**: linear mV/°C; read ADC and apply the datasheet
  transfer function (mind offset — TMP36 has 500 mV offset).
- **Digital (DS18B20, DHT, BMP/BME)**: talk over 1-Wire/I2C; use the vendor library.
  More accurate, no ADC scaling headaches.

### Ultrasonic / Time-of-Flight distance
- **Ultrasonic (HC-SR04)**: trigger a pulse, measure echo pin HIGH time.
  `distance_cm = echo_us / 58`. 5 V part — level-shift the echo pin for 3.3 V MCUs.
  Blind zone <2 cm, cone spread, fooled by soft/angled surfaces.
- **ToF (VL53L0X/L1X)**: laser, I2C, mm resolution, small beam. Better indoors and for
  short precise ranges; affected by ambient IR / reflectivity.

### IMU (accelerometer/gyro/mag)
- I2C or SPI (MPU-6050, ICM-20948, BNO055). Raw gyro drifts, accel is noisy — fuse
  them (complementary or Kalman filter) for stable orientation. BNO055 fuses on-chip.
- Set full-scale range and sample rate per datasheet; calibrate offsets at rest.

### Encoders (position/speed)
- **Incremental quadrature**: two channels A/B 90° apart → direction + counts.
  Use interrupts or a hardware quadrature counter; debounce mechanical types.
  Speed = counts per time window; position = accumulated counts (relative).
- **Absolute**: reports exact angle over I2C/SPI/PWM (e.g. AS5600) — no homing needed.

## Signal Filtering / Debouncing
- **Moving average / median** for noisy analog: median rejects spikes well.
- **Exponential (IIR) filter**: `y += alpha * (x - y);` (0<alpha<1) — cheap low-pass.
- Physical: RC low-pass at the ADC pin. Match cutoff to signal bandwidth.
- Oversample-and-average to gain effective ADC bits on slow signals.
- Debounce mechanical contacts (see arduino-patterns.md).

## Driving Actuators

### LEDs — resistor sizing
Never connect an LED directly across a supply; it needs current limiting.

    R = (V_supply - V_f) / I_led

- V_f (forward voltage): ~1.8–2.2 V red, ~3.0–3.4 V blue/white — **check datasheet**.
- I_led: typ 5–20 mA for indicators. Example: 5 V, V_f 2 V, 10 mA →
  R = (5−2)/0.010 = 300 Ω (use 330 Ω). Verify pin current limit too.
- Power in resistor: `P = I² · R` — usually tiny, but check for high-current LEDs.

### Relays
- Coils need more current than a pin sources and generate a large inductive kick.
- Drive via a transistor/MOSFET, **flyback diode across the coil** (cathode to +V).
- Prefer opto-isolated relay modules for mains. Keep mains wiring away from logic;
  treat mains as dangerous — if unsure, don't.

### Servos (hobby RC)
- 3-wire: V+, GND, signal. Position set by ~50 Hz PWM, 1.0–2.0 ms pulse (1.5 ms center).
- Use the `Servo` library. **Power from a separate 5–6 V supply**, common ground —
  stall current can be >1 A and browns out the MCU.

### DC motors
- Even small motors exceed pin current and inject noise. Drive through a MOSFET
  (low-side) or an H-bridge (for direction). PWM the gate/enable for speed.
- **Flyback/freewheel diode** across the motor (or use an H-bridge with built-in
  diodes). Add a small cap across the motor terminals to suppress brush noise.

### Steppers
- Need a dedicated driver (ULN2003 for small unipolar; A4988/DRV8825/TMC bipolar).
- Bipolar drivers do current limiting via Vref — set it per the datasheet to protect
  motor and driver. Microstepping smooths motion at the cost of torque per step.

## Why a Driver / MOSFET / Flyback Diode?

- **Current**: MCU pins source milliamps; motors/relays/solenoids want hundreds of mA
  to amps. A transistor/MOSFET lets a small gate signal switch a big load.
- **Flyback diode**: an inductive load (coil, motor) resists current change; when you
  switch it off, the collapsing field spikes hundreds of volts. The diode gives that
  current a safe loop, protecting the switch. **Mandatory** on relays, solenoids,
  motors.
- **Isolation**: optocouplers/opto-relays separate logic ground from high-voltage or
  noisy domains.

## Safety Checklist
- [ ] Separate supply for motors/servos, common ground with MCU?
- [ ] Flyback diode on every inductive load?
- [ ] LED/load current within resistor and pin limits?
- [ ] Level shifting for 5 V sensor outputs into 3.3 V pins?
- [ ] Motor/brush noise decoupled (caps) so ADC/logic stays clean?
- [ ] LiPo: never short, don't over-discharge (<3.0 V/cell), charge on a proper
      balance charger, never leave unattended.
