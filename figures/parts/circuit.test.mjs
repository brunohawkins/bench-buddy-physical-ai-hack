// node parts/circuit.test.mjs — the solver against hand calculations.
import { solve, commit } from "./circuit.js";
let fail = 0;
const check = (name, got, want, tol) => { const ok = Math.abs(got - want) <= tol; if (!ok) fail++; console.log(`${ok ? "ok  " : "FAIL"} ${name}: ${got.toFixed(4)} (want ${want} ± ${tol})`); };
const LED = { is: 1e-18, n: 2 };              // red LED: ~1.8–2.0 V at a few mA

// 1. Divider: 5 V across 1k + 1k → 2.5 V.
{ const c = { nodes: 3, ground: 0, elements: [{ kind: "V", p: 1, n: 0, v: 5, r: 1e-3 }, { kind: "R", a: 1, b: 2, r: 1000 }, { kind: "R", a: 2, b: 0, r: 1000 }] };
  check("divider midpoint (V)", solve(c).v[2], 2.5, 1e-3); }

// 2. 5 V → 220 Ω → red LED: I = (5 − Vf)/220 with Vf ≈ 1.9 V.
{ const c = { nodes: 4, ground: 0, elements: [{ kind: "V", p: 1, n: 0, v: 5, r: 1e-3 }, { kind: "R", a: 1, b: 2, r: 220 }, { kind: "D", a: 2, k: 3, ...LED }, { kind: "R", a: 3, b: 0, r: 5 }] };
  const r = solve(c); const i = r.currents[1];
  check("LED forward voltage (V)", r.v[2] - r.v[3], 1.95, 0.2); check("LED current (mA)", i * 1000, 13.9, 1.5);
  console.log("     converged", r.converged, "in", r.iterations, "iterations"); }

// 3. Reversed LED: no current.
{ const c = { nodes: 3, ground: 0, elements: [{ kind: "V", p: 1, n: 0, v: 5, r: 1e-3 }, { kind: "R", a: 1, b: 2, r: 220 }, { kind: "D", a: 0, k: 2, ...LED }] };
  check("reversed LED current (µA)", solve(c).currents[1] * 1e6, 0, 0.01); }

// 4. NPN switch: 5 V, base through 10k, collector LED + 220 Ω → saturates, LED ~13 mA.
{ const c = { nodes: 5, ground: 0, elements: [{ kind: "V", p: 1, n: 0, v: 5, r: 1e-3 }, { kind: "R", a: 1, b: 2, r: 10000 }, { kind: "NPN", b: 2, c: 4, e: 0, is: 1e-14, bf: 150, br: 2 }, { kind: "R", a: 1, b: 3, r: 220 }, { kind: "D", a: 3, k: 4, ...LED }] };
  const r = solve(c); check("NPN base (V)", r.v[2], 0.7, 0.12); check("NPN collector (V)", r.v[4], 0.1, 0.15); check("LED via NPN (mA)", r.currents[3] * 1000, 13.5, 1.8); }

// 5. Logic-level MOSFET: gate 5 V, drain load 100 Ω from 5 V → drain near 0.
{ const c = { nodes: 4, ground: 0, elements: [{ kind: "V", p: 1, n: 0, v: 5, r: 1e-3 }, { kind: "R", a: 1, b: 2, r: 100 }, { kind: "NMOS", g: 3, d: 2, s: 0, vth: 1.5, kp: 10 }, { kind: "R", a: 1, b: 3, r: 1 }] };
  check("MOSFET drain on (V)", solve(c).v[2], 0.01, 0.05); }

// 6. RC charge: 5 V, 10k, 10 µF; after one time constant (0.1 s) the cap is at 63.2 %.
{ const c = { nodes: 3, ground: 0, elements: [{ kind: "V", p: 1, n: 0, v: 5, r: 1e-3 }, { kind: "R", a: 1, b: 2, r: 10000 }, { kind: "C", a: 2, b: 0, c: 10e-6, key: "c1" }] };
  const state = {}; let r; const dt = 1e-4;
  for (let t = 0; t < 1000; t++) { r = solve(c, { dt, state, guess: r?.v }); commit(c, r.v, state); }
  check("RC at t = RC (V)", r.v[2], 5 * (1 - Math.exp(-1)), 0.01); }

console.log(fail ? `${fail} failed` : "all passed");
process.exit(fail ? 1 : 0);
