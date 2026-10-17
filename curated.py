"""Hand-checked projects the tutor can run instead of an LLM-written plan. Owner: L.

radar_led is the demo (from radar-led-demo.md). 555 wraps project.py, which fsm.py (--script) still uses.
A step's check is "confirm" (the user says it's done), "vision" (expect_rows), "look" (the vision model
checks the step from the photo, the part list and the conversation; "ask" says what it should see) or
"measure" (needs the Arduino).
"""
import project

RADAR_LED = {
    "id": "radar_led",
    "name": "radar presence LED",
    "circuit": "Radar V -> + supply rail; G -> - supply rail. IO -> row 30 -> 1 kilohm resistor -> row 35 "
               "-> LED anode; LED cathode -> row 36 -> jumper -> the same ground rail as G. All row junctions "
               "must share the same a-e or f-j half. TX and RX remain unplugged. Use the user's identified "
               "lead colours, not colour conventions. LED polarity and resistor value may need user confirmation.",
    "match": "a light that turns on when someone walks up: radar, presence, motion or people sensor with an LED",
    "required": [
        {"desc": "an LD2402 radar module", "type": ("other", "ic"), "keywords": ("radar", "ld2402", "hlk")},
        {"desc": "an LED", "type": ("led",)},
        {"desc": "a 1 kilohm resistor", "type": ("resistor",), "range": (220, 1000)},
        {"desc": "a breadboard", "type": ("other",), "keywords": ("breadboard",)},
    ],
    "steps": [
        {"id": "radar", "say": "Look where the radar's five coloured leads join its little board: they're labelled V, G, IO, "
                               "TX and RX. Tell me which colour goes to which label.",
         "why": "V and G are power, IO is the output that goes high when it sees someone, TX and RX are serial and "
                "stay unplugged. Knowing the colours lets me check your wiring.",
         "check": {"kind": "confirm"}},
        {"id": "power", "say": "Plug the radar's V lead into the plus rail and its G lead into the minus rail.",
         "why": "V and G power the module. If the silkscreen says 3.3 volts, use the 3.3 volt supply instead.",
         "check": {"kind": "look", "ask": "The radar's V lead is in a + power rail and its G lead is in a - power rail "
                                          "(lead colours as said at the bench)."}},
        {"id": "io", "say": "Plug the IO lead into row 30. Then put one leg of the 1 kilohm resistor in row 30 and the other "
                            "leg in row 35.",
         "why": "IO goes high, about 3.3 volts, when it detects someone. The resistor limits the LED's current so "
                "it doesn't overload the radar's IO pin. Holes in the same row are connected.",
         "check": {"kind": "look", "ask": "The radar's IO lead is in row 30, and a resistor has one leg in row 30 and the "
                                          "other in row 35 (same half of the board)."}},
        {"id": "led", "say": "Put the LED's long leg in row 35 and its short leg in row 36.",
         "why": "The long leg is the positive side, the anode, so it joins the resistor. Current only flows from long "
                "leg to short leg.",
         "check": {"kind": "look", "ask": "An LED has its legs in row 35 and row 36 (same half as the resistor)."}},
        {"id": "ground", "say": "Use a jumper wire to connect row 36 to the minus rail.",
         "why": "That closes the loop back to ground, so current can flow when IO goes high.",
         "check": {"kind": "look", "ask": "A jumper wire connects row 36 to a - power rail."}},
        {"id": "usb", "say": "Now power the rails: 5 volts to the plus rail and ground to the minus rail.",
         "why": "The rails carry the 5 volts and ground to the radar.",
         "check": {"kind": "confirm"}},
        {"id": "finish", "say": "Now walk in front of the radar. Did the LED light up?",
         "why": "The radar sees you, IO goes high, and current flows through the resistor and LED.",
         "check": {"kind": "confirm"}},
    ],
    "done": "It works! The radar sees you, drives IO high, and lights the LED. Say it's not working if it stops.",
    "troubleshooting": [
        "Power: is V on the 5 volt rail and G on ground? If the silkscreen says 3.3 V, power it from 3.3 V.",
        "LED direction: the long leg must face the resistor, the short leg ground. Backwards, it never lights.",
        "Rows: the resistor end and the LED long leg must share a row; a leg one row off breaks the circuit.",
        "Dim LED: at about 1 mA through 1 kilohm it is dim but visible; shade it with a hand or use 220 ohms.",
        "Warm-up: the radar can take a few seconds after power-up before it detects anything.",
        "If it still never lights, IO may be outputting serial data instead of on/off; that needs a script.",
    ],
}

P555 = {
    "id": "555",
    "name": "555 LED blinker",
    "match": "an LED that blinks or flashes using a 555 timer chip",
    "required": None,                    # uses project.missing()
    "steps": project.STEPS + [{"id": "finish", "say": "Measuring the blink rate.", "why": "",
                               "check": {"kind": "freq"}}],
    "done": "Your blinker is working. Tell me if anything stops working.",
    "troubleshooting": [],               # debug.probe() reads the test points instead
}

PROJECTS = {p["id"]: p for p in (RADAR_LED, P555)}


def missing(proj: dict, parts: list[dict]) -> list[str]:
    """Spoken descriptions of the project's required parts that aren't in `parts`."""
    if proj["required"] is None:
        return project.missing(parts)
    return [need["desc"] for need in proj["required"] if not any(_has(need, p) for p in parts)]


def _has(need: dict, part: dict) -> bool:
    if part.get("type") not in need["type"]:
        return False
    if "keywords" in need:
        name = str(part.get("part", "")).lower()
        return any(k in name for k in need["keywords"])
    if "range" in need:
        lo, hi = need["range"]
        return part.get("value") is not None and lo * 0.99 <= part["value"] <= hi * 1.01
    return True
