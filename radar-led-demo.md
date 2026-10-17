# Radar presence LED: quick demo circuit

No-code circuit for the hackathon demo video. The LD2402 radar detects a person and its IO output lights an LED directly, with no microcontroller or code. A Jetson Nano and CSI camera sit beside it with a live preview, so the shot is: person walks up, LED lights, camera is already watching.

## Bill of materials

| Qty | Part | Notes |
|---|---|---|
| 1 | LD2402 radar module (XIITIA HLK-LD2402, 24 GHz) | Pins: V, G, IO, TX, RX |
| 1 | Breadboard | Half-size is fine |
| 1 | LED | Any colour; red or green shows best on camera |
| 1 | 1 kΩ resistor | 220 Ω also works but may overload the radar's IO pin |
| 1 | USB cable plus breakout or breadboard power module | Takes 5V and GND from the laptop |
| 4-5 | Jumper wires | 2 for power, 1 for IO, 1 for LED to GND |
| 1 | Jetson Nano and CSI camera | Powered from its own adapter, not wired to the radar |
| optional | 100 µF capacitor | Across the 5V and GND rails if the LED flickers |

Not needed: Arduino Uno, Raspberry Pi.

## Wiring

| Radar pin | Connect to |
|---|---|
| V | 5V rail (from laptop USB) |
| G | GND rail |
| IO | 1 kΩ resistor, then LED long leg (+) |
| TX | nothing |
| RX | nothing |

LED short leg (-) goes to the GND rail. TX and RX are serial data pins and stay unconnected for this demo.

```
Laptop USB 5V ──── V  ┐
                      │ LD2402
Laptop USB GND ─┬─ G  │ radar
                │  IO ┴── 1k ── LED(+) ─ LED(-) ──┐
                └─────────── GND rail ────────────┘

Jetson Nano ←── CSI ribbon ── Camera   (own power, separate)
```

## One-minute build order

1. Plug the radar into the breadboard.
2. Connect V and G to the 5V and GND rails.
3. Connect IO to one end of the resistor.
4. Connect the other end of the resistor to the LED's long leg.
5. Connect the LED's short leg to the GND rail.
6. Plug in the USB power.

## Notes and risks

- IO is the presence output; it should go high when someone is detected (about 3.3 V). Confirm against the datasheet or silkscreen.
- Confirm whether the module takes 5V on V. If the silkscreen says 3.3V, power it from 3.3V instead.
- At about 1 mA through 1 kΩ the LED will be dim but visible indoors. For a brighter LED, add a transistor or use two LEDs.
- If the LED never lights, the module may be outputting serial on IO instead of an on/off level. Fallback: read its serial output from the Jetson with a short script.
- The Jetson Nano can draw more than a laptop USB port supplies, so give it its own power supply to avoid brownouts mid-demo.
