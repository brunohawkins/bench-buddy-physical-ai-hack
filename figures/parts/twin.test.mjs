// node parts/twin.test.mjs — the radar LED demo and a 555 blinker, simulated from their layouts.
import { breadboard } from "./components/demo.js";
import { createTwin } from "./twin.js";
let fail = 0;
const check = (name, ok, detail) => { if (!ok) fail++; console.log(`${ok ? "ok  " : "FAIL"} ${name}${detail ? ` · ${detail}` : ""}`); };
const holes = breadboard({ labels: false }).root.userData.holes;

// The layout the gallery's "Radar demo layout" builds (copied from its JSON).
const radarDemo = { parts: [
  { id: "breadboard-power-mb102", title: "Power module", pins: { "left − 1": "back − rail by row 2", "left − 2": "back − rail by row 3", "left + 1": "back + rail by row 2", "left + 2": "back + rail by row 3", "right − 1": "front − rail by row 2", "right − 2": "front − rail by row 3", "right + 1": "front + rail by row 2", "right + 2": "front + rail by row 3" } },
  { id: "hlk-ld2402-radar", title: "Radar", pins: { V: "j18", G: "j19", IO: "j20", TX: "j21", RX: "j22" } },
  { id: "resistor-1k", title: "R1 1k", pins: { 1: "g20", 2: "g24" } },
  { id: "led-5mm-red", title: "LED", pins: { "+ (anode)": "f24", "− (cathode)": "f25" } },
  { id: "capacitor-100uf", title: "C1", pins: { "+": "front + rail by row 9", "−": "front − rail by row 9" } },
  { id: "jumper-wire", title: "Red wire", pins: { "end A": "h18", "end B": "back + rail by row 12" } },
  { id: "jumper-wire", title: "Black wire", pins: { "end A": "h19", "end B": "back − rail by row 14" } },
  { id: "jumper-wire", title: "Green wire", pins: { "end A": "h25", "end B": "back − rail by row 26" } },
] };

const t = createTwin({ holes });
t.setLayout(radarDemo);
const led = () => t.results.parts.find((p) => p.title === "LED");
check("rails at 5 V", Math.abs(t.voltageAt("back + rail by row 20") - 5) < 0.1, `${t.voltageAt("back + rail by row 20").toFixed(2)} V`);
check("nobody there: LED off", led().glow < 0.01, led().text);
check("radar over-voltage warning", t.results.warnings.some((w) => /3.0–3.6/.test(w)));
t.set("presence", true);
check("person present: IO high", Math.abs(t.voltageAt("f20") - 3.3) < 0.3, `${t.voltageAt("f20").toFixed(2)} V`);
check("person present: LED on, ~1.3 mA", led().glow > 0.05 && /ON/.test(led().text), led().text);
t.set("usb", false);
check("USB unplugged: everything off", t.voltageAt("j18") < 0.05 && led().glow < 0.01, led().text);
t.set("usb", true);
console.log("\n" + t.describe() + "\n");

// Fault finding: the user's LED is in backwards; the Arduino reads 3.3 V at the LED anode row
// while the simulation (correctly built) would show ~1.8 V.
t.measure("h24", 3.2);
let d = t.diagnose();
console.log("     after one reading:", d.likely.map((h) => h.text).join(" | "), "→ probe", d.next?.hole);
check("one reading: reversed LED among the likely faults, and a next probe", d.likely.some((h) => /backwards/.test(h.text)) && d.next);
// Simulate taking the suggested reading on the real (faulty) board: reverse the LED in a copy and read it there.
const truth = createTwin({ holes });
truth.setLayout({ parts: radarDemo.parts.map((p) => (p.title === "LED" ? { ...p, pins: { "+ (anode)": "f25", "− (cathode)": "f24" } } : p)) });
truth.set("presence", true);
t.measure(d.next.hole, truth.voltageAt(d.next.hole));
d = t.diagnose();
console.log("     after two readings:", d.likely.map((h) => h.text).join(" | "));
check("two readings: reversed LED is the top explanation", /backwards/.test(d.likely[0].text) || d.likely.slice(0, 2).some((h) => /backwards/.test(h.text)));

// 555 astable: R1 10k, R2 68k, C 10 µF → f = 1.44 / ((R1 + 2 R2) C) ≈ 0.99 Hz.
const blinker = { parts: [
  { id: "breadboard-power-mb102", title: "Power module", pins: radarDemo.parts[0].pins },
  { id: "ic-ne555-dip8", title: "NE555", pins: { 1: "e10", 2: "e11", 3: "e12", 4: "e13", 5: "f13", 6: "f12", 7: "f11", 8: "f10" } },
  { id: "jumper-wire", title: "GND", pins: { "end A": "a10", "end B": "front − rail by row 9" } },
  { id: "jumper-wire", title: "VCC", pins: { "end A": "j10", "end B": "back + rail by row 9" } },
  { id: "jumper-wire", title: "RESET", pins: { "end A": "a13", "end B": "j10".replace("j10", "front + rail by row 14") } },
  { id: "resistor-10k", title: "R1", pins: { 1: "i10", 2: "i7" } },
  { id: "jumper-wire", title: "R1 to DIS", pins: { "end A": "j7", "end B": "j11" } },
  { id: "resistor-1k", title: "R2 (68k)", pins: { 1: "h11", 2: "h12" } },
  { id: "jumper-wire", title: "THR-TRIG", pins: { "end A": "g12", "end B": "b11" } },
  { id: "capacitor-100uf", title: "C (10 µF)", pins: { "+": "c11", "−": "front − rail by row 12" } },
  { id: "resistor-220r", title: "R3", pins: { 1: "b12", 2: "b16" } },
  { id: "led-5mm-red", title: "LED", pins: { "+ (anode)": "c16", "− (cathode)": "c17" } },
  { id: "jumper-wire", title: "LED GND", pins: { "end A": "a17", "end B": "front − rail by row 17" } },
] };
console.log("555: values below use the catalogue's 1k/100 µF stand-ins, so f = 1.44/((10k+2·1k)·100 µF) ≈ 1.2 Hz");
const t5 = createTwin({ holes });
t5.setLayout(blinker);
let edges = 0, last = null, first = null;
for (let k = 0; k < 400; k++) {             // 4 s in 10 ms frames
  const r = t5.step(0.01);
  const on = r.parts.find((p) => p.title === "LED").glow > 0.1;
  if (last !== null && on && !last) { edges++; if (first === null) first = t5.time; }
  last = on;
}
check("555 blinks", edges >= 3, `${edges} rising edges in 4 s · ${t5.results.parts.find((p) => p.title === "NE555").text}`);
console.log(fail ? `${fail} failed` : "all passed");
process.exit(fail ? 1 : 0);
