// Bench Buddy projects as breadboard layouts. Each has:
//   devices  off-board boards on the bench (pins are referred to as "<Device> <pin>")
//   base     what is already built before the steps start
//   steps    keyed by the FSM's step ids (project.py STEPS): what the step places, the row vision
//            checks it in (so a "row 14, should be 13" failure can be drawn where it really went),
//            and inputs it switches (e.g. plugging in the Arduino)
//   probes   the Arduino pins wired to test points, and which hole each one reads
//   nodes    debug.py's node names → probe pin, so "pin 4 is at 0.02 volts" becomes a reading
const w = (title, a, b, colour = "red") => ({ id: "jumper-wire", title, colour, pins: { "end A": a, "end B": b } });

// The MB102 power module on the left end of the rails (USB from a laptop).
const MB102 = { id: "breadboard-power-mb102", title: "Power module (MB102)", rot: 3, pins: { "left − 1": "back − rail by row 2", "left − 2": "back − rail by row 3", "left + 1": "back + rail by row 2", "left + 2": "back + rail by row 3", "right − 1": "front − rail by row 2", "right − 2": "front − rail by row 3", "right + 1": "front + rail by row 2", "right + 2": "front + rail by row 3" } };

export const PROJECTS = {
  "blinker-555": {
    title: "555 blinker (Bench Buddy's current project)",
    board: "breadboard-half",
    inputs: { arduino: false, usb: false },
    devices: [{ id: "arduino-uno", name: "Arduino", at: [-88, 0], rot: 0 }],
    base: [
      { id: "ic-ne555-dip8", title: "NE555", pins: { 1: "e10", 2: "e11", 3: "e12", 4: "e13", 5: "f13", 6: "f12", 7: "f11", 8: "f10" } },
      w("VCC wire (pin 8)", "j10", "back + rail by row 9"),
      w("GND wire (pin 1)", "a10", "front − rail by row 9", "black"),
      { id: "resistor-10k", title: "R1 10 kΩ", span: 3, pins: { 1: "i7", 2: "i10" } },
      w("R1 to pin 7", "j7", "j11", "yellow"),
      { id: "resistor-68k", title: "R2 68 kΩ", span: 3, pins: { 1: "h11", 2: "h14" } },
      w("R2 to pin 6", "i14", "i12", "yellow"),
      w("Pin 6 to pin 2", "g12", "b11", "orange"),
      { id: "capacitor-10uf", title: "C1 10 µF", rot: 0, pins: { "+": "c11", "−": "c10" } },
      { id: "resistor-10k", title: "Pull-down 10 kΩ (pin 4)", span: 3, pins: { 1: "d10", 2: "d13" } },
      { id: "capacitor-ceramic-10nf", title: "C2 10 nF (pin 5)", span: 2, pins: { 1: "g13", 2: "g15" } },
      w("C2 to GND", "j15", "back − rail by row 15", "black"),
      { id: "resistor-330r", title: "R3 330 Ω", span: 4, pins: { 1: "b12", 2: "b16" } },
      { id: "led-5mm-red", title: "LED", rot: 2, pins: { "+ (anode)": "a16", "− (cathode)": "a17" } },
      w("LED to GND", "c17", "front − rail by row 18", "black"),
      w("+ rails joined", "back + rail by row 29", "front + rail by row 29"),
      w("− rails joined", "back − rail by row 30", "front − rail by row 30", "black"),
      w("Arduino 5V", "Arduino 5V", "front + rail by row 3"),
      w("Arduino GND", "Arduino GND", "front − rail by row 3", "black"),
      w("Probe A0 (pin 8)", "Arduino A0", "g10", "blue"),
      w("Probe A1 (pins 2/6)", "Arduino A1", "d11", "blue"),
      w("Probe A2 (pin 4)", "Arduino A2", "b13", "blue"),
      w("Probe D2 (pin 3)", "Arduino D2", "d12", "green"),
    ],
    steps: {
      reset: { row: 13, place: [w("Reset jumper (pin 4 → 5 V)", "a13", "front + rail by row 14")] },
      "power-on": { inputs: { arduino: true } },
    },
    probes: { A0: "g10", A1: "d11", A2: "b13", D2: "d12" },
    nodes: { "VCC (pin 8)": "A0", "RESET (pin 4)": "A2", "TIMING (pins 2/6)": "A1", "OUT (pin 3)": "D2" },
  },
  // Matches curated.py RADAR_LED (the tutor's demo) on the real full-size board: the radar sits beside
  // the board and its coloured leads plug in; the laptop's USB powers the rails (drawn as an MB102).
  "radar-led": {
    title: "Radar presence LED (radar-led-demo.md)",
    board: "breadboard-full",
    inputs: { usb: false, presence: false },
    devices: [{ id: "hlk-ld2402-radar", name: "Radar", at: [-20, -52], rot: 0, lift: 9.5 }],
    base: [MB102],
    steps: {
      power: { place: [w("Radar V lead", "Radar V", "front + rail by row 26"), w("Radar G lead", "Radar G", "front − rail by row 27", "black")] },
      io: { row: 30, place: [w("Radar IO lead", "Radar IO", "a30", "yellow"), { id: "resistor-1k", title: "R1 1 kΩ", span: 5, pins: { 1: "b30", 2: "b35" } }] },
      led: { row: 35, place: [{ id: "led-5mm-red", title: "LED", rot: 2, pins: { "+ (anode)": "c35", "− (cathode)": "c36" } }] },
      ground: { row: 36, place: [w("LED to − rail", "a36", "front − rail by row 38", "black")] },
      usb: { inputs: { usb: true } },
    },
    probes: {},
    nodes: {},
  },
};

// Move a placement to the row vision actually saw: every lettered hole shifts by `by` rows.
export function shiftRows(part, by) {
  const pins = {};
  for (const [name, hole] of Object.entries(part.pins)) {
    const m = /^([a-j])(\d+)$/.exec(hole);
    pins[name] = m ? `${m[1]}${+m[2] + by}` : hole;
  }
  return { ...part, pins, title: `${part.title} (where vision saw it)`, wrong: true };
}

// The twin layout for a project: devices (as parts whose pins are named terminals), the base,
// then the given steps' placements.
import { UNO_PINS } from "./components/demo.js";
const DEVICE_PINS = { "arduino-uno": Object.keys(UNO_PINS), "hlk-ld2402-radar": ["V", "G", "IO", "TX", "RX"] };
export function layoutOf(project, steps = []) {
  const parts = project.devices.map((d) => ({ id: d.id, title: d.name, device: true, pins: Object.fromEntries(DEVICE_PINS[d.id].map((n) => [n, `${d.name} ${n}`])) }));
  parts.push(...project.base);
  for (const id of steps) parts.push(...(project.steps[id]?.place ?? []));
  return { parts };
}
