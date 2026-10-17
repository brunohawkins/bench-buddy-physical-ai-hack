// node parts/projects.test.mjs — Bench Buddy's 555 blinker, simulated as the FSM's fake run goes.
import { breadboard } from "./components/demo.js";
import { createTwin } from "./twin.js";
import { PROJECTS, layoutOf, shiftRows } from "./projects.js";
let fail = 0;
const check = (name, ok, detail) => { if (!ok) fail++; console.log(`${ok ? "ok  " : "FAIL"} ${name}${detail ? ` · ${detail}` : ""}`); };
const holes = breadboard({ labels: false }).root.userData.holes;
const P = PROJECTS["blinker-555"];
const t = createTwin({ holes });
for (const [k, v] of Object.entries(P.inputs)) t.set(k, v);

// Vision: "That went into row 14, it should be row 13." → draw the jumper in row 14.
t.setLayout({ parts: [...layoutOf(P).parts, ...P.steps.reset.place.map((p) => shiftRows(p, 1))] });
check("wrong-row jumper is drawn in a14", t.netOf("a14").pins.some((x) => /where vision saw it/.test(x)));
// Retry passes → the jumper in a13.
t.setLayout(layoutOf(P, ["reset"]));
// Power-on: plug in the Arduino.
t.set("arduino", true);
const vcc = t.voltageAt(P.probes.A0);
check("A0 (pin 8) reads ~5 V like the real 4.98 V", Math.abs(vcc - 4.98) < 0.15, `${vcc.toFixed(2)} V`);
check("A2 (pin 4) high: reset tied to 5 V", t.voltageAt(P.probes.A2) > 4.5, `${t.voltageAt(P.probes.A2).toFixed(2)} V`);
// Let it run 6 s and time the LED.
let rises = [], last = false;
for (let k = 0; k < 600; k++) {
  const r = t.step(0.01);
  const on = r.parts.find((p) => p.title === "LED").glow > 0.2;
  if (on && !last) rises.push(t.time);
  last = on;
}
const period = (rises.at(-1) - rises[1]) / (rises.length - 2);
check("blinks at ~0.99 Hz (predict() says 0.99, the fake bench measured 0.97)", Math.abs(1 / period - 0.99) < 0.12, `${(1 / period).toFixed(2)} Hz over ${rises.length - 1} periods`);
check("twin.blinkHz agrees", Math.abs(t.blinkHz - 1 / period) < 0.05, `${t.blinkHz.toFixed(2)} Hz`);
console.log("     " + t.results.parts.find((p) => p.title === "NE555").text, "·", t.results.parts.find((p) => p.title === "LED").text);

// Debug: the fake bench reads A2 at 0.02 V (reset jumper pulled). Simulation says ~5 V → mismatch → why?
t.measure(P.probes.A0, 4.98);
const mm = t.measure(P.probes.A2, 0.02);
check("A2 reading disagrees with the simulation", mm.some((m) => m.hole === P.probes.A2), JSON.stringify(mm));
const d = t.diagnose();
console.log("     likely:", d.likely.map((h) => h.text).join(" | "), d.next ? `· next probe ${d.next.hole}` : "");
check("diagnosis: the reset jumper isn't connected", d.likely.slice(0, 3).some((h) => /Reset jumper/.test(h.text)));
console.log(fail ? `${fail} failed` : "all passed");
process.exit(fail ? 1 : 0);
