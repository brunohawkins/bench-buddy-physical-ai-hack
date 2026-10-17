// What each catalogue part does electrically. model(id) returns a builder that, given the nets its
// pins landed on, emits solver elements (circuit.js) and later reports the part's state.
//
// build({ pin, node, inputs, key }) → { elements, report(v, currents) → { text, glow?, warnings? }, after?(v) }
//   pin(name) → net index of that pin (or a fresh floating node if the pin isn't connected)
//   node()    → a new internal node
//   inputs    → the bench inputs (power, presence, buttons …)
//   key       → a unique prefix for this part's state

const LED_RED = { is: 1e-18, n: 2.0 };

const resistor = (ohms) => ({ pin }) => {
  const el = { kind: "R", a: pin("1"), b: pin("2"), r: ohms };
  return {
    elements: [el],
    report: (v, i) => ({ text: `${fmtV(v[el.a] - v[el.b])} across, ${fmtI(i(el))}`, warnings: Math.abs(v[el.a] - v[el.b]) ** 2 / ohms > 0.25 ? [`dissipating ${(Math.abs(v[el.a] - v[el.b]) ** 2 / ohms).toFixed(2)} W, over its ¼ W rating`] : [] }),
  };
};

const diode = (params, rs, label) => ({ pin, node }) => {
  const mid = node();
  const r = { kind: "R", a: pin("A (anode)"), b: mid, r: rs };
  const d = { kind: "D", a: mid, k: pin("K (cathode, banded end)"), ...params };
  return {
    elements: [r, d],
    report: (v, i) => {
      const I = i(r);
      return { text: I > 1e-6 ? `conducting ${fmtI(I)}, ${fmtV(v[r.a] - v[d.k])} drop` : `${label} blocking`, warnings: I > (params.max ?? 1) ? [`${fmtI(I)} is over its rating`] : [] };
    },
  };
};

const capacitor = (farads, polar, rating = 16) => ({ pin, key }) => {
  const a = pin(polar ? "+" : "1"), b = pin(polar ? "−" : "2");
  const el = { kind: "C", a, b, c: farads, key: `${key}:c` };
  const leak = { kind: "R", a, b, r: polar ? 2e6 : 1e9 };
  return {
    elements: [el, leak],
    report: (v) => {
      const vc = v[a] - v[b];
      const warnings = [];
      if (polar && vc < -0.5) warnings.push(`reversed: − lead is ${fmtV(-vc)} above +, it can bulge or vent`);
      if (Math.abs(vc) > rating) warnings.push(`${fmtV(vc)} is over its ${rating} V rating`);
      return { text: `charged to ${fmtV(vc)}`, warnings };
    },
  };
};

const led = ({ pin, node }) => {
  const mid = node();
  const r = { kind: "R", a: pin("+ (anode)"), b: mid, r: 12 };
  const d = { kind: "D", a: mid, k: pin("− (cathode)"), ...LED_RED };
  return {
    elements: [r, d],
    report: (v, i) => {
      const I = i(r);
      const glow = Math.min(1, Math.sqrt(Math.max(0, I) / 0.012));   // perceived brightness: full at ~12 mA
      const warnings = I > 0.03 ? [`${fmtI(I)} through the LED will burn it out (max 20–30 mA): add a resistor`] : [];
      const rev = v[d.k] - v[r.a] > 4 ? ["reverse biased by more than 4 V"] : [];
      return { text: I > 50e-6 ? `ON · ${fmtI(I)} · ${fmtV(v[r.a] - v[d.k])}` : v[d.k] > v[r.a] + 0.5 ? "OFF · it's in backwards" : "OFF", glow, warnings: [...warnings, ...rev] };
    },
  };
};

const npn = ({ pin }) => {
  const el = { kind: "NPN", b: pin("B"), c: pin("C"), e: pin("E"), is: 1e-14, bf: 200, br: 2 };
  return { elements: [el], report: (v, i) => ({ text: v[el.b] - v[el.e] > 0.55 ? `on · collector ${fmtI(i(el))}` : "off" }) };
};

const nmos = ({ pin }) => {
  const el = { kind: "NMOS", g: pin("G"), d: pin("D"), s: pin("S"), vth: 1.5, kp: 10 };
  return { elements: [el], report: (v, i) => ({ text: v[el.g] - v[el.s] > el.vth ? `on · ${fmtI(i(el))} drain` : "off" }) };
};

// 4-pin tactile switch: pins 1–2 and 3–4 are always joined; pressing joins the two pairs.
const tactile = ({ pin, inputs, key }) => {
  const pressed = !!inputs.buttons?.[key];
  const els = [{ kind: "R", a: pin("1"), b: pin("2"), r: 0.02 }, { kind: "R", a: pin("3"), b: pin("4"), r: 0.02 }, { kind: "R", a: pin("1"), b: pin("3"), r: pressed ? 0.05 : 1e9 }];
  return { elements: els, report: () => ({ text: pressed ? "pressed" : "released" }), button: true };
};

// NE555 (bipolar): internal 5k/5k/5k divider, comparators on THR and TRIG, a set/reset latch,
// discharge transistor on pin 7 and a totem-pole output that swings to about VCC − 1.7 V.
const timer555 = ({ pin, node, key }) => {
  const P = (n) => pin(String(n));
  const gnd = P(1), vcc = P(8), ctrl = P(5), mid = node();
  const st = { q: false };
  const out = {
    kind: "B",
    at: (v) => {
      const supply = v[vcc] - v[gnd];
      const high = st.q && supply > 3 ? Math.max(0, supply - 1.7) : 0.1;
      const g = 1 / 10;
      return [{ a: P(3), b: gnd, g }, { a: gnd, b: P(3), i: (v[gnd] + high) * g - v[gnd] * g }];
    },
  };
  const dis = { kind: "B", at: () => (st.q ? [] : [{ a: P(7), b: gnd, g: 1 / 15 }]) };
  return {
    elements: [
      { kind: "R", a: vcc, b: ctrl, r: 5000 }, { kind: "R", a: ctrl, b: mid, r: 5000 }, { kind: "R", a: mid, b: gnd, r: 5000 },
      { kind: "R", a: vcc, b: gnd, r: 1700 }, { kind: "R", a: P(2), b: gnd, r: 1e8 }, { kind: "R", a: P(6), b: gnd, r: 1e8 }, { kind: "R", a: P(4), b: vcc, r: 1e8 },
      out, dis,
    ],
    // Latch update between time steps: reset beats trigger beats threshold.
    after: (v) => {
      const supply = v[vcc] - v[gnd], vc = v[ctrl] - v[gnd];
      if (supply < 3 || v[P(4)] - v[gnd] < 0.7) st.q = false;
      else if (v[P(2)] - v[gnd] < vc / 2) st.q = true;
      else if (v[P(6)] - v[gnd] > vc) st.q = false;
    },
    report: (v) => {
      const supply = v[vcc] - v[gnd];
      if (supply < 3) return { text: `not powered (${fmtV(supply)} across pins 8–1)` };
      if (v[P(4)] - v[gnd] < 0.7) return { text: `held in reset: pin 4 at ${fmtV(v[P(4)] - v[gnd])}`, warnings: ["pin 4 (reset) must be tied high to run"] };
      return { text: `running · output ${st.q ? "HIGH" : "LOW"} (${fmtV(v[P(3)] - v[gnd])})`, warnings: supply > 16 ? ["supply over 16 V"] : [] };
    },
    state: st,
  };
};

// HLK-LD2402: draws ~50 mA, drives IO high (~3.3 V) while someone is present, idles UART TX high.
const radar = ({ pin, inputs }) => {
  const V = pin("V"), G = pin("G"), IO = pin("IO"), TX = pin("TX");
  const powered = (v) => v[V] - v[G] > 2.8;
  const drive = (a, level, rOut) => ({ kind: "B", at: (v) => (powered(v) ? [{ a, b: G, g: 1 / rOut }, { a: G, b: a, i: (v[G] + level) / rOut - v[G] / rOut }] : []) });
  return {
    elements: [{ kind: "R", a: V, b: G, r: 66 }, drive(IO, inputs.presence ? 3.3 : 0, 100), drive(TX, 3.3, 1000), { kind: "R", a: pin("RX"), b: G, r: 1e7 }],
    report: (v) => {
      const s = v[V] - v[G];
      const warnings = s > 3.6 ? [`supply is ${fmtV(s)}; many LD2402 listings rate it 3.0–3.6 V, so power it from 3V3 if yours does`] : [];
      if (s < 2.8) return { text: `off (${fmtV(s)} supply)`, warnings };
      return { text: `${inputs.presence ? "person detected · IO HIGH" : "no one there · IO LOW"} (${fmtV(v[IO] - v[G])})`, warnings };
    },
  };
};

// MB102: USB (or jack) in, switch, and per-side jumper choosing 5 V, OFF or 3.3 V for that rail pair.
const mb102 = ({ pin, inputs }) => {
  const on = inputs.usb && inputs.mbSwitch !== false;
  const side = (s) => inputs.jumpers?.[s] ?? "5V";
  const els = [];
  for (const s of ["left", "right"]) {
    const plus = pin(`${s} + 1`), minus = pin(`${s} − 1`);
    els.push({ kind: "R", a: pin(`${s} + 1`), b: pin(`${s} + 2`), r: 0.01 }, { kind: "R", a: pin(`${s} − 1`), b: pin(`${s} − 2`), r: 0.01 });
    if (on && side(s) !== "OFF") els.push({ kind: "V", p: plus, n: minus, v: side(s) === "3V3" ? 3.3 : 5.0, r: side(s) === "3V3" ? 0.4 : 0.15, source: s });
  }
  els.push({ kind: "R", a: pin("left − 1"), b: pin("right − 1"), r: 0.01 });
  return {
    elements: els,
    ground: () => pin("left − 1"),
    report: (v, i) => {
      if (!inputs.usb) return { text: "no power: USB unplugged" };
      if (inputs.mbSwitch === false) return { text: "switched off" };
      const draw = els.filter((e) => e.kind === "V").reduce((sum, e) => sum + i(e), 0);
      const warnings = draw > 0.5 ? [`drawing ${fmtI(draw)}: more than a laptop USB port gives (0.5 A)`] : [];
      return { text: `on · left ${side("left")}, right ${side("right")} · ${fmtI(draw)} from USB`, warnings };
    },
  };
};

// Arduino Uno: when its USB is in, 5 V (through the polyfuse and cable, ~0.3 Ω) between 5V and GND;
// A0–A2 and D2 are high-impedance inputs, read like the bench's serial READ / FREQ commands.
const arduino = ({ pin, inputs }) => {
  const on = inputs.arduino !== false;
  const els = [{ kind: "R", a: pin("GND"), b: pin("GND 2"), r: 0.01 }];
  if (on) els.push({ kind: "V", p: pin("5V"), n: pin("GND"), v: 5.0, r: 0.3 });
  const inputsUsed = ["A0", "A1", "A2", "D2"];
  for (const p of inputsUsed) els.push({ kind: "R", a: pin(p), b: pin("GND"), r: 1e8 });
  return {
    elements: els,
    ground: () => pin("GND"),
    report: (v, i) => {
      if (!on) return { text: "USB unplugged: no power" };
      const g = v[pin("GND")];
      const draw = i(els[1]);
      const read = inputsUsed.map((p) => `${p} ${fmtV(v[pin(p)] - g)}`).join(" · ");
      return { text: `on · ${fmtI(draw)} from 5V · ${read}`, warnings: draw > 0.45 ? [`drawing ${fmtI(draw)} from the Arduino's 5 V pin (about 0.5 A max over USB)`] : [] };
    },
  };
};

const wire = ({ pin }) => {
  const el = { kind: "R", a: pin("end A"), b: pin("end B"), r: 0.02 };
  return { elements: [el], report: (v, i) => ({ text: `${fmtI(i(el))}` }), flow: el };
};

const MODELS = {
  "resistor-1k": resistor(1000), "resistor-220r": resistor(220), "resistor-10k": resistor(10000),
  "led-5mm-red": led,
  "capacitor-100uf": capacitor(100e-6, true), "capacitor-10uf": capacitor(10e-6, true, 25),
  "capacitor-ceramic-100nf": capacitor(100e-9, false, 50), "capacitor-ceramic-10nf": capacitor(10e-9, false, 50),
  "resistor-68k": resistor(68000), "resistor-330r": resistor(330),
  "diode-1n4007": diode({ is: 7e-9, n: 1.8, max: 1 }, 0.04, "1N4007"), "diode-1n4148": diode({ is: 2.5e-9, n: 1.75, max: 0.2 }, 0.6, "1N4148"),
  "transistor-2n2222a": npn, "mosfet-irlz44n": nmos,
  "button-tactile-6mm": tactile, "ic-ne555-dip8": timer555,
  "hlk-ld2402-radar": radar, "breadboard-power-mb102": mb102,
  "jumper-wire": wire, "jumper-wires-mm": wire,
  "arduino-uno": arduino,
};

export const modelOf = (id) => MODELS[id] ?? null;

export const fmtV = (x) => `${Math.abs(x) < 0.0005 ? "0.00" : x.toFixed(2)} V`;
export const fmtI = (x) => { const a = Math.abs(x); return a >= 1 ? `${x.toFixed(2)} A` : a >= 1e-3 ? `${(x * 1e3).toFixed(1)} mA` : a >= 1e-6 ? `${(x * 1e6).toFixed(0)} µA` : "0 mA"; };
