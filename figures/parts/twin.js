// The bench twin: what is physically on the user's breadboard, turned into a circuit and simulated.
//
//   const twin = createTwin({ holes });          // the breadboard's named holes
//   twin.setLayout(layout)                       // { parts: [{ id, title, pins: { name: hole } }] }
//   twin.set("usb", true) / ("presence", true) / ("jumpers", { left: "5V" }) / ("buttons", { … })
//   twin.step(seconds)                           // advance (capacitors, 555 …); DC parts settle at once
//   twin.results                                 // nets with voltages, parts with state and warnings
//   twin.measure(hole, volts) → compares with the simulation; twin.diagnose() explains a mismatch
//   twin.apply(event)                            // the same as the above, from one JSON event
//
// Nets: each numbered row's a–e and f–j strips, each rail, and anything joined to them by a part
// lead or a jumper wire. Wires are 20 mΩ resistors so their current shows.
import { solve, commit } from "./circuit.js";
import { modelOf, fmtV } from "./electrical.js";

const DT = 1e-3;

export function stripOf(hole) {
  const m = /^([a-j])(\d+)$/.exec(hole);
  if (m) return `${m[1] <= "e" ? "a–e" : "f–j"} row ${m[2]}`;
  const r = /^(front|back) ([+−]) rail/.exec(hole);
  if (r) return `${r[1]} ${r[2]} rail`;
  return hole;
}

export function createTwin({ holes }) {
  const holeNames = holes.map((h) => h.name);
  const inputs = { usb: true, mbSwitch: true, jumpers: { left: "5V", right: "5V" }, presence: false, buttons: {} };
  let layout = { parts: [] };
  let built = null;            // { circuit, parts, strips, netOfStrip, holesOfNet, ground }
  let guess = null;
  const state = {};            // capacitor voltages
  const measurements = new Map();
  const listeners = new Set();
  let time = 0;
  const edges = [];            // recent 555 output rising edges (simulated seconds)
  let edgesSince = 0;          // edges since the layout last changed

  function build({ skip = null, reverse = null } = {}) {
    // 1. Strips (breadboard metal) that something is plugged into are the base nodes.
    const strips = [...new Set(layout.parts.flatMap((p) => Object.values(p.pins)).map(stripOf))];
    const stripIndex = new Map(strips.map((s, i) => [s, i]));
    let nodes = strips.length;
    const elements = [];
    const parts = [];
    layout.parts.forEach((p, index) => {
      const make = modelOf(p.id);
      if (!make) { parts.push({ index, p, model: null }); return; }
      const key = `p${index}`;
      const pins = { ...p.pins };
      if (reverse === index) {                                 // fault hypothesis: polarised part the other way round
        const names = Object.keys(pins);
        if (names.length === 2) [pins[names[0]], pins[names[1]]] = [pins[names[1]], pins[names[0]]];
      }
      const cache = new Map();
      const pin = (name) => {
        if (cache.has(name)) return cache.get(name);
        const hole = pins[name];
        const floating = !hole || (skip && skip.part === index && (skip.pin === null || skip.pin === name));
        const n = floating ? nodes++ : stripIndex.get(stripOf(hole)) ?? nodes++;   // not in the board: its own floating node
        cache.set(name, n);
        return n;
      };
      for (const name of Object.keys(pins)) pin(name);           // resolve every pin now, so nodes is final before solving
      const node = () => nodes++;
      const m = make({ pin, node, inputs, key });
      elements.push(...m.elements);
      parts.push({ index, p, model: m, key });
    });
    // 2. Ground: the power module's − rail if there is one, else any source's − terminal.
    let ground = 0;
    const mb = parts.find((x) => x.model?.ground);
    const src = elements.find((e) => e.kind === "V");
    if (mb) ground = mb.model.ground(); else if (src) ground = src.n;
    // Nets: strips joined by near-zero resistors become one net for display.
    const parent = Array.from({ length: nodes }, (_, i) => i);
    const find = (x) => (parent[x] === x ? x : (parent[x] = find(parent[x])));
    for (const e of elements) if (e.kind === "R" && e.r <= 0.05) parent[find(e.a)] = find(e.b);
    return { circuit: { nodes, ground, elements }, parts, strips, stripIndex, find };
  }

  function run(b, seconds, st, g, track = false) {
    let r = null;
    const steps = Math.max(1, Math.round(seconds / DT));
    for (let k = 0; k < steps; k++) {
      r = solve(b.circuit, { dt: DT, state: st, guess: g });
      g = r.v;
      commit(b.circuit, r.v, st);
      for (const x of b.parts) {
        if (!x.model?.after) continue;
        const was = x.model.state?.q;
        x.model.after(r.v);
        if (track && x.model.state && !was && x.model.state.q) { edges.push(time + (k + 1) * DT); edgesSince++; }   // 555 output went high
      }
    }
    while (edges.length > 6) edges.shift();
    return { r, guess: g };
  }

  function report(b, r) {
    const idx = new Map(b.circuit.elements.map((e, i) => [e, i]));
    const cur = (e) => r.currents[idx.get(e)];
    const warnings = [];
    const parts = b.parts.map(({ index, p, model }) => {
      if (!model) return { index, title: p.title, text: "no electrical model (off-board part)" };
      const rep = model.report(r.v, cur);
      for (const w of rep.warnings ?? []) warnings.push(`${p.title}: ${w}`);
      const flow = model.flow ? cur(model.flow) : undefined;
      return { index, title: p.title, ...rep, flow };
    });
    // Nets for display: group strips by connectivity.
    const nets = new Map();
    b.strips.forEach((s, i) => {
      const root = b.find(i);
      if (!nets.has(root)) nets.set(root, { strips: [], holes: [], pins: [], v: r.v[i] });
      nets.get(root).strips.push(s);
    });
    for (const h of holeNames) { const si = b.stripIndex.get(stripOf(h)); if (si !== undefined) nets.get(b.find(si)).holes.push(h); }
    for (const { p } of b.parts) for (const [name, hole] of Object.entries(p.pins)) {
      const n = nets.get(b.find(b.stripIndex.get(stripOf(hole))));
      if (n) n.pins.push(/^end [AB]$/.test(name) ? p.title : `${p.title} ${name}`);
    }
    const g0 = r.v.length ? r.v[b.circuit.ground] : 0;
    const list = [...nets.values()].filter((n) => n.pins.length).map((n) => ({ ...n, label: labelOf(n), v: n.v - g0 }));
    return { time, converged: r.converged, parts, nets: list, warnings, v: r.v };
  }

  function labelOf(n) {
    const rail = n.strips.find((s) => s.includes("rail"));
    const pins = n.pins.slice(0, 2).join(", ") + (n.pins.length > 2 ? ` +${n.pins.length - 2}` : "");
    return rail ? `${rail}${pins ? ` · ${pins}` : ""}` : pins || n.strips[0];
  }

  const api = {
    inputs,
    results: null,
    get time() { return time; },
    setLayout(next) {
      edges.length = 0;
      edgesSince = 0;
      layout = { parts: (next.parts ?? []).map((p) => ({ ...p, pins: { ...p.pins } })) };
      built = build();
      guess = null;
      api.step(0.02);
    },
    set(key, value) {
      edgesSince = 0;
      if (key === "jumpers" || key === "buttons") Object.assign(inputs[key], value);
      else inputs[key] = value;
      built = build();
      api.step(0.002);
    },
    step(seconds) {
      if (!built) built = build();
      const { r, guess: g } = run(built, seconds, state, guess, true);
      guess = g;
      time += seconds;
      api.results = report(built, r);
      api.results.mismatches = compare();
      for (const fn of listeners) fn(api.results);
      return api.results;
    },
    netOf(hole) {
      if (!api.results) return null;
      const net = api.results.nets.find((n) => n.holes.includes(hole));
      if (net) return net;
      const sameStrip = holeNames.filter((h) => stripOf(h) === stripOf(hole));
      return { holes: sameStrip, v: null, label: `${stripOf(hole)} (nothing connected)`, pins: [] };
    },
    voltageAt(hole) { return api.netOf(hole)?.v ?? 0; },
    // The simulated blink rate from the 555's last few output edges (0 if it isn't oscillating).
    get blinkHz() {
      // Skip the first edge after a change: the first cycle charges from 0 V, not from VCC/3, so it runs long.
      const e = edgesSince > 0 ? edges.slice(-Math.min(edges.length, edgesSince - 1)) : [];
      return e.length >= 3 && time - e.at(-1) < 3 ? (e.length - 1) / (e.at(-1) - e[0]) : 0;
    },
    // A real reading (e.g. the Arduino on A0) at a hole.
    measure(hole, volts) { measurements.set(hole, volts); api.results && (api.results.mismatches = compare()); return api.results?.mismatches; },
    clearMeasurements() { measurements.clear(); },
    // Which single fault best explains the readings? Tries each lead out of its hole, each part
    // missing, and each two-lead polarised part reversed, and ranks by how well they match.
    diagnose() {
      if (!measurements.size) return { likely: [], next: null };
      const sim = (b) => {
        const { r } = run(b, 0.05, {}, null);
        const at = (hole) => { const i = b.stripIndex.get(stripOf(hole)); return i === undefined ? 0 : r.v[i] - r.v[b.circuit.ground]; };
        let err = 0;
        for (const [hole, mv] of measurements) err += Math.abs(at(hole) - mv);
        return { err, at };
      };
      const hyps = [{ text: "nothing wrong (as built)", ...sim(build()) }];
      layout.parts.forEach((p, i) => {
        hyps.push({ text: `${p.title} is missing or not pushed in`, ...sim(build({ skip: { part: i, pin: null } })) });
        for (const name of Object.keys(p.pins)) hyps.push({ text: `${p.title}: the ${name} lead isn't making contact in ${p.pins[name]}`, ...sim(build({ skip: { part: i, pin: name } })) });
        if (/led|diode|capacitor-100uf/.test(p.id)) hyps.push({ text: `${p.title} is in backwards`, ...sim(build({ reverse: i })) });
      });
      hyps.sort((a, b) => a.err - b.err);
      // Everything within 0.15 V of the best fit is equally likely: say so, and pick the hole whose
      // voltage differs most between those explanations, so one more reading separates them.
      const likely = hyps.filter((h) => h.err <= hyps[0].err + 0.15).slice(0, 6);
      let next = null;
      if (likely.length > 1) {
        const candidates = [...new Set(layout.parts.flatMap((p) => Object.values(p.pins)))].filter((h) => !measurements.has(h));
        let best = 0;
        for (const hole of candidates) {
          const vs = likely.map((h) => h.at(hole));
          const spread = Math.max(...vs) - Math.min(...vs);
          if (spread > best + 1e-3) { best = spread; next = { hole, spread: +spread.toFixed(2) }; }
        }
      }
      return { likely: likely.map((h) => ({ text: h.text, err: +h.err.toFixed(3) })), next };
    },
    on(fn) { listeners.add(fn); return () => listeners.delete(fn); },
    // One JSON event from Bench Buddy (or a test): layout, place, remove, set, measure.
    apply(ev) {
      switch (ev.type) {
        case "layout": return api.setLayout(ev.layout);
        case "place": return api.setLayout({ parts: [...layout.parts, ev.part] });
        case "remove": return api.setLayout({ parts: layout.parts.filter((p) => !(p.id === ev.id && (!ev.hole || Object.values(p.pins).includes(ev.hole)))) });
        case "set": return api.set(ev.key, ev.value);
        case "measure": return api.measure(ev.hole, ev.volts ?? ev.mv / 1000);
        default: return null;
      }
    },
    describe() {
      const r = api.results;
      if (!r) return "";
      return [...r.nets.map((n) => `${fmtV(n.v).padStart(8)}  ${n.label}`), ...r.parts.map((p) => `${p.title}: ${p.text}`), ...r.warnings.map((w) => `⚠ ${w}`)].join("\n");
    },
  };

  function compare() {
    const out = [];
    for (const [hole, mv] of measurements) {
      const sim = api.voltageAt(hole);
      if (Math.abs(sim - mv) > Math.max(0.25, 0.1 * Math.abs(sim))) out.push({ hole, measured: mv, simulated: +sim.toFixed(3) });
    }
    return out;
  }
  return api;
}
