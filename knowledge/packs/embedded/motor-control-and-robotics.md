---
priority: support
domain: embedded
aspect: morrigan
summary: DC/servo/stepper differences, H-bridge/stepper drivers, PWM speed, encoder closed-loop, PID tuning, power budget.
---

# Motor Control and Robotics

Getting mechanical motion under control: choose the motor, drive it safely, close the
loop, and budget the power.

## Motor Types

| Type    | Control input          | Feedback     | Strengths | Watch out |
|---------|------------------------|--------------|-----------|-----------|
| DC brushed | voltage/PWM + direction | none (open) | cheap, fast, simple | no position, brush noise/wear |
| Servo (hobby) | PWM pulse width → angle | internal (to its range) | easy positioning, integrated | limited travel/torque, jitter |
| Stepper | step + direction pulses | none (open, counts steps) | precise open-loop position | can lose steps if overloaded, draws current at rest |
| BLDC    | commutation (ESC)      | hall/sensorless | efficient, powerful | needs ESC/complex driver |

- **DC**: speed ∝ voltage (via PWM), torque ∝ current. Reverse by swapping polarity
  (H-bridge).
- **Servo**: a small geared DC motor + pot + control board; you command an angle.
  ~50 Hz, 1.0–2.0 ms pulse (1.5 ms ≈ center). Continuous-rotation servos map pulse to
  speed instead.
- **Stepper**: moves in fixed steps (e.g. 1.8° = 200 steps/rev). Position is known by
  counting **if** it never skips. Holds position with holding torque (draws current
  hot even at standstill).

## Drivers

You almost never drive a motor from an MCU pin. Use a driver.

- **H-bridge** (DC): four switches let current flow either direction → forward/reverse
  + brake/coast. Chips: DRV8871, TB6612FNG (efficient), L298N (old, lossy). Enable pin
  takes PWM for speed; two direction pins set polarity.
- **Stepper driver**: A4988 / DRV8825 / TMC2209. You feed STEP + DIR pulses; the driver
  sequences the coils and does microstepping.
- **Current limiting** (critical for steppers, and DC stall): set the driver's Vref
  per the datasheet so coil current stays within the motor/driver rating. Too high →
  overheating; too low → weak/stalling. **Check the driver datasheet** for the
  Vref↔current formula (depends on sense resistor).
- Provide flyback protection (H-bridges include body diodes) and heatsinking for
  sustained current.

## PWM Speed Control

- Average voltage to the motor = `duty * V_supply`. Higher duty → faster.
- Choose PWM frequency high enough to be inaudible and smooth (often 15–25 kHz for DC
  motors) but not so high the driver can't switch cleanly.
- Below a minimum duty the motor won't overcome static friction (deadband) — map your
  command so 0 stays off and useful range starts above the deadband.
- Decel/brake vs coast: H-bridge can short the motor terminals to brake.

## Closed-Loop Control with Encoders

Open loop (stepper/PWM) guesses; closed loop measures. Add an encoder (quadrature or
absolute — see sensors doc) to know real position/speed, then correct error.

- Speed control: measure counts per time window, adjust PWM to hit target.
- Position control: drive toward a target count; slow as you approach.
- Handle direction from the encoder's A/B phase; watch for missed counts at high speed
  (use interrupts or a hardware quadrature decoder).

## PID Control (intro)

PID computes a correction from the **error** = setpoint − measured.

    output = Kp*e + Ki*∫e dt + Kd*de/dt

- **P (proportional)** — reacts to current error. Higher Kp = stiffer/faster but too
  high oscillates. Alone it leaves steady-state error (offset).
- **I (integral)** — accumulates past error to eliminate steady-state offset. Too much
  = slow oscillation and overshoot. Add **anti-windup**: clamp the integral when the
  output saturates.
- **D (derivative)** — reacts to rate of change, damps overshoot. Sensitive to noise —
  filter the derivative or the measurement.

**Practical tuning (manual / Ziegler–Nichols-lite)**
1. Set Ki = Kd = 0. Raise Kp until the output oscillates steadily (that's Ku, period Tu).
2. Back Kp off to ~0.5–0.6·Ku for stability.
3. Add Ki to remove the remaining offset; increase until response is snappy without
   growing oscillation.
4. Add Kd to damp overshoot/ringing; keep small if the signal is noisy.
5. Fix your **loop rate** (constant dt) — PID math assumes regular sampling. Use
   millis()/timer, not a variable loop.
6. Clamp output to actuator limits and apply anti-windup.

Symptoms: constant offset → need more I. Overshoot/ringing → less P or more D.
Buzzing/jitter → too much D on a noisy signal, or dt too small.

## Power Budgeting

- Size the supply for **stall/inrush**, not nominal. A motor's stall current can be
  5–10× running current — check the datasheet.
- Sum worst-case current of all motors + logic + peripherals; add margin (~30%).
- Voltage: motor rated voltage sets the rail; the MCU gets a separate regulated rail.
  **Common ground** always.
- Battery: capacity (mAh) ÷ average current ≈ runtime; account for sag under load and
  discharge cutoff. LiPo: respect C-rating, don't over-discharge (<3.0 V/cell), use a
  balance charger, fuse high-current runs.
- Add bulk capacitance near drivers to absorb current spikes; keep high-current loops
  short and thick. Decouple logic from motor noise (separate wiring, caps, star
  ground).
