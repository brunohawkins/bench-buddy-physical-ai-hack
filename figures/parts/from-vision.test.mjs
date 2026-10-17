// node parts/from-vision.test.mjs — vision's board list (vlm.py "board") → twin layout → simulation.
import { breadboard } from "./components/demo.js";
import { createTwin } from "./twin.js";
import { fromVision, twinParts, twinHole, leadsFrom } from "./from-vision.js";
let fail = 0;
const check = (name, ok, detail) => { if (!ok) fail++; console.log(`${ok ? "ok  " : "FAIL"} ${name}${detail ? ` · ${detail}` : ""}`); };
const holes = breadboard({ rows: 63, labels: false }).root.userData.holes;
const names = new Set(holes.map((h) => h.name));

check("full board has a63 and j63", names.has("a63") && names.has("j63"));
check("+top20 → front + rail by row 20", twinHole("+top20") === "front + rail by row 20" && names.has(twinHole("+top20")));
check("-bottom12 → back − rail by row 12", twinHole("-bottom12") === "back − rail by row 12" && names.has(twinHole("-bottom12")));
check("rail gap row 13 snaps to 14", twinHole("top-13") === "front − rail by row 14" && names.has(twinHole("top-13")));
check("off-board hole is dropped", twinHole("k5") === null && twinHole("a99") === null);
check("leadsFrom: 'red is V, black goes to G and yellow is IO'", JSON.stringify(leadsFrom("red is V, black goes to G and yellow is IO")) === JSON.stringify({ red: "V", black: "G", yellow: "IO" }));

// The finished radar build as the vision model reports it: leads plugged in with their far ends on the radar.
const BUILD = [
  { id: "wire1", part: "wire", colour: "red", holes: ["+top26"] },
  { id: "wire2", part: "wire", colour: "black", holes: ["-top27"] },
  { id: "wire3", part: "wire", colour: "yellow", holes: ["a30"] },
  { id: "r1", part: "resistor", colour: null, holes: ["b30", "b35"] },
  { id: "led", part: "led", colour: "red", holes: ["c36", "c35"] },
  { id: "wire4", part: "wire", colour: "black", holes: ["a36", "-top38"] },
];
const sim = (board, inputs) => {
  const { layout, unplaced } = fromVision({ board }, inputs);
  const t = createTwin({ holes });
  for (const [k, v] of Object.entries(layout.inputs)) t.set(k, v);
  t.setLayout(twinParts(layout));
  t.step(0.05);
  const led = t.results.parts.find((p) => p.title === "LED");
  return { t, layout, unplaced, glow: led?.glow ?? 0, led };
};

let r = sim(BUILD, { usb: true, presence: false });
check("radar leads wired by where they went", ["V", "G", "IO"].every((p) => r.layout.parts.some((x) => x.pins["end A"] === `Radar ${p}`)));
check("LED anode faces the resistor even when listed second", r.layout.parts.find((p) => p.id === "led-5mm-red").pins["+ (anode)"] === "c35");
check("nobody there: LED off", r.glow < 0.05, `glow ${r.glow.toFixed(3)}`);
r = sim(BUILD, { usb: true, presence: true });
check("someone there: LED lit", r.glow > 0.05, `glow ${r.glow.toFixed(3)} · ${r.led?.text}`);
r = sim(BUILD, { usb: false, presence: true });
check("no USB power: LED off", r.glow < 0.05, `glow ${r.glow.toFixed(3)}`);

// LED one row off (36/37): the resistor's row 35 goes nowhere, so it never lights.
const off = BUILD.map((p) => (p.id === "led" ? { ...p, holes: ["c36", "c37"] } : p));
r = sim(off, { usb: true, presence: true });
check("LED a row off stays dark", r.glow < 0.05, `glow ${r.glow.toFixed(3)}`);

// Colours from the conversation win over position.
const { layout } = fromVision({ board: [{ id: "w", part: "wire", colour: "green", holes: ["a30"] }] }, { leads: { green: "TX" } });
check("lead colour map from the tutor is used", layout.parts.some((p) => p.pins["end A"] === "Radar TX"));
check("unknown parts are reported, not drawn", fromVision({ board: [{ id: "x", part: "other", holes: ["a1"] }] }).unplaced.length === 1);

console.log(fail ? `${fail} failed` : "all passed");
process.exit(fail ? 1 : 0);
