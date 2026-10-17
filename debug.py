"""Ordered probe over the test points; the first failure wins. Owner: H.

| Pin | Node      | Healthy             |
| A0  | pin 8     | ~5.0 V              |
| A2  | pin 4     | ~5.0 V              |
| A1  | pins 2/6  | swings ~1.7-3.3 V   |
| D2  | pin 3     | ~1 Hz               |
"""
from contracts import ProbeResult


def probe(bench) -> ProbeResult:
    mv = bench.read("A0")
    if mv < 4500:
        return ProbeResult(False, "VCC (pin 8)", f"pin 8 is at {mv / 1000:.2f} volts",
                           "The chip isn't getting power. Check the jumper from pin 8 to the 5 volt rail.")

    mv = bench.read("A2")
    if mv < 800:
        return ProbeResult(False, "RESET (pin 4)", f"pin 4 is at {mv / 1000:.2f} volts",
                           "The chip is held in reset. Tie pin 4 to the 5 volt rail.")

    lo, hi, mean = bench.sample("A1", 3000)
    if hi - lo < 500:
        if mean < 1000:
            return ProbeResult(False, "TIMING (pins 2/6)", f"the timing capacitor is stuck at {mean / 1000:.2f} volts",
                               "The capacitor never charges. Check R2 and the capacitor on pins 2 and 6.")
        return ProbeResult(False, "TIMING (pins 2/6)", f"the timing capacitor is stuck at {mean / 1000:.2f} volts",
                           "The capacitor never discharges. Check R1 and the pin 7 connection.")

    hz = bench.freq(4000)
    if hz == 0:
        return ProbeResult(False, "OUT (pin 3)", "there are no pulses on pin 3",
                           "The timer is running but nothing reaches the output. Check pin 3, the 330 ohm resistor and the LED.")

    return ProbeResult(True, None, f"the output is running at {hz:.2f} hertz", "Everything measures healthy.")
