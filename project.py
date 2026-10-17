"""The 555 blinker as data. Owners: L + H.

Row numbers are placeholders until H fixes the breadboard layout.
"""

R1, R2, C = 10_000, 68_000, 10e-6

# What the user must have. "part" matches by substring, so "NE555P" and "LM555" count as a 555.
REQUIRED = [
    {"type": "ic", "part": "555", "qty": 1},
    {"type": "resistor", "value": 10_000, "qty": 2},     # R1 + pin 4 pull-down
    {"type": "resistor", "value": 68_000, "qty": 1},
    {"type": "resistor", "value": 330, "qty": 1},
    {"type": "capacitor", "value": 10e-6, "qty": 1},
    {"type": "capacitor", "value": 100e-9, "qty": 1},
    {"type": "capacitor", "value": 10e-9, "qty": 1},
    {"type": "led", "qty": 1},
]

# The board is pre-built apart from these. check.kind is "vision" or "measure".
STEPS = [
    {"id": "reset", "say": "Connect pin 4 to the 5 volt rail with a red wire.",
     "check": {"kind": "vision", "expect_rows": [13], "wire_colour": "red"}},
    {"id": "power-on", "say": "Plug in the Arduino.",
     "check": {"kind": "measure", "pin": "A0", "expect_mv": [4500, 5300]}},
]


def _matches(need: dict, have: dict) -> bool:
    if need["type"] != have.get("type"):
        return False
    if "part" in need:
        return need["part"] in str(have.get("part", "")).upper()
    if "value" in need:
        value = have.get("value")
        return value is not None and abs(value - need["value"]) <= 0.01 * need["value"]
    return True


def missing(parts: list[dict]) -> list[str]:
    """Spoken descriptions of required parts the user doesn't have enough of."""
    out = []
    for need in REQUIRED:
        have = sum(p.get("qty", 1) for p in parts if _matches(need, p))
        if have < need["qty"]:
            out.append(describe(need))
    return out


def describe(part: dict) -> str:
    if part["type"] == "resistor":
        num, prefix = _si(part["value"])
        return f"a {num} {prefix + ' ' if prefix else ''}ohm resistor"
    if part["type"] == "capacitor":
        num, prefix = _si(part["value"])
        return f"a {num} {prefix}farad capacitor"
    if part["type"] == "ic":
        return f"a {part['part']} timer chip"
    return f"an {part['type'].upper()}" if part["type"] == "led" else f"a {part['type']}"


def _si(value: float) -> tuple[str, str]:
    """68000 -> ("68", "k"), 1e-5 -> ("10", "micro")."""
    for scale, prefix in ((1e6, "mega"), (1e3, "k"), (1, ""), (1e-6, "micro"), (1e-9, "nano"), (1e-12, "pico")):
        if value >= scale * 0.999:
            return f"{value / scale:.3g}", prefix
    return f"{value:g}", ""
