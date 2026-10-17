// Circuit solver for the breadboard simulation. Plain JS, no three.js: runs in the browser and Node.
//
// solve(circuit, { dt, state }) finds the operating point (dt = 0) or takes one time step (dt > 0)
// by nodal analysis, Newton–Raphson for the non-linear parts. Sources are Norton equivalents (a
// conductance and a current), so the only unknowns are node voltages.
//
// A circuit is { nodes, ground, elements }. Element kinds (a/b/… are node indices):
//   R    { a, b, r }                     resistor; wires and closed switches are small R
//   C    { a, b, c, key }                capacitor: open at DC, backward-Euler companion when dt > 0
//   V    { p, n, v, r }                  voltage source with internal resistance r
//   D    { a, k, is, n }                 Shockley diode (add series resistance as an R)
//   NPN  { b, c, e, is, bf, br }         Ebers–Moll transport model
//   NMOS { g, d, s, vth, kp }            square-law MOSFET, body tied to source
//   B    { at(v, dt, state) → stamps }   behavioural: returns [{ a, b, g, i }] for this iteration
// Capacitor voltages live in `state` (keyed by element key) and advance with commit().

const VT = 0.025852;
const GMIN = 1e-12;

export function solve(circuit, { dt = 0, state = {}, guess = null, maxIter = 150 } = {}) {
  const N = circuit.nodes;
  if (!N) return { v: new Float64Array(0), converged: true, iterations: 0, currents: [] };
  const gnd = circuit.ground ?? 0;
  const v = guess && guess.length === N ? Float64Array.from(guess) : new Float64Array(N);
  const junction = new Map();                                    // last limited junction voltage per element
  let converged = false, iter = 0;
  for (; iter < maxIter; iter++) {
    const A = Array.from({ length: N }, () => new Float64Array(N));
    const z = new Float64Array(N);
    const s = {
      g(a, b, g) { A[a][a] += g; A[b][b] += g; A[a][b] -= g; A[b][a] -= g; },
      i(a, b, i) { z[a] -= i; z[b] += i; },                        // current i through the element, a → b
      vccs(a, b, cp, cn, gm) { A[a][cp] += gm; A[a][cn] -= gm; A[b][cp] -= gm; A[b][cn] += gm; },
    };
    for (let n = 0; n < N; n++) A[n][n] += GMIN;
    junction.limited = false;
    for (const e of circuit.elements) stamp(e, v, s, dt, state, junction);
    for (let j = 0; j < N; j++) A[gnd][j] = 0;
    A[gnd][gnd] = 1; z[gnd] = 0;
    const next = gauss(A, z);
    if (!next) break;
    let delta = 0;
    for (let n = 0; n < N; n++) {
      let d = next[n] - v[n];
      if (Math.abs(d) > 3) d = Math.sign(d) * 3;
      v[n] += d;
      delta = Math.max(delta, Math.abs(d));
    }
    if (delta < 1e-6 && iter > 0 && !junction.limited) { converged = true; break; }
  }
  return { v, converged, iterations: iter + 1, currents: currents(circuit, v, dt, state) };
}

// After a converged time step: remember capacitor voltages for the next one.
export function commit(circuit, v, state) {
  for (const e of circuit.elements) if (e.kind === "C") state[e.key] = v[e.a] - v[e.b];
}

function pnjlim(vnew, vold, nvt, vcrit) {
  if (vnew > vcrit && Math.abs(vnew - vold) > 2 * nvt) {
    if (vold > 0) {
      const arg = 1 + (vnew - vold) / nvt;
      return arg > 0 ? vold + nvt * Math.log(arg) : vcrit;
    }
    return nvt * Math.log(vnew / nvt);
  }
  return vnew;
}
const vcritOf = (is, nvt) => nvt * Math.log(nvt / (Math.SQRT2 * is));

function junctionV(junction, key, raw, is, nvt) {
  const old = junction.has(key) ? junction.get(key) : 0;
  const lim = pnjlim(raw, old, nvt, vcritOf(is, nvt));
  junction.set(key, lim);
  if (Math.abs(lim - raw) > 1e-6) junction.limited = true;   // not converged while a junction is still being stepped
  return lim;
}

function stamp(e, v, s, dt, state, junction) {
  switch (e.kind) {
    case "R": s.g(e.a, e.b, 1 / e.r); break;
    case "C":
      if (dt > 0) {
        const g = e.c / dt, prev = state[e.key] ?? 0;
        s.g(e.a, e.b, g);
        s.i(e.a, e.b, -g * prev);
      }
      break;
    case "V": {
      const g = 1 / e.r;
      s.g(e.p, e.n, g);
      s.i(e.n, e.p, e.v * g);
      break;
    }
    case "D": {
      const nvt = e.n * VT;
      const vd = junctionV(junction, e, v[e.a] - v[e.k], e.is, nvt);
      const [id, gd] = diode(vd, e.is, nvt);
      s.g(e.a, e.k, gd);
      s.i(e.a, e.k, id - gd * vd);
      break;
    }
    case "NPN": {
      const vbe = junctionV(junction, e, v[e.b] - v[e.e], e.is, VT);
      const vbc = junctionV(junction, (e._bc ??= {}), v[e.b] - v[e.c], e.is, VT);
      const ef = Math.exp(vbe / VT), er = Math.exp(vbc / VT);
      const gf = (e.is / VT) * ef, gr = (e.is / VT) * er;
      const ibe = (e.is / e.bf) * (ef - 1), ibc = (e.is / e.br) * (er - 1);
      const gbe = gf / e.bf + GMIN, gbc = gr / e.br + GMIN;
      s.g(e.b, e.e, gbe); s.i(e.b, e.e, ibe - gbe * vbe);
      s.g(e.b, e.c, gbc); s.i(e.b, e.c, ibc - gbc * vbc);
      const ict = e.is * (ef - er);                                // c → e
      s.vccs(e.c, e.e, e.b, e.e, gf);
      s.vccs(e.c, e.e, e.b, e.c, -gr);
      s.i(e.c, e.e, ict - gf * vbe + gr * vbc);
      break;
    }
    case "NMOS": {
      const flip = v[e.d] < v[e.s];
      const d = flip ? e.s : e.d, src = flip ? e.d : e.s;
      const vgs = v[e.g] - v[src], vds = v[d] - v[src];
      const vov = vgs - e.vth;
      let id = 0, gm = 0, gds = 1e-9;
      if (vov > 0) {
        if (vds < vov) { id = e.kp * (vov * vds - vds * vds / 2); gm = e.kp * vds; gds = e.kp * (vov - vds) + 1e-9; }
        else { const lam = 0.01; id = (e.kp / 2) * vov * vov * (1 + lam * vds); gm = e.kp * vov * (1 + lam * vds); gds = (e.kp / 2) * vov * vov * lam + 1e-9; }
      }
      s.g(d, src, gds);
      s.vccs(d, src, e.g, src, gm);
      s.i(d, src, id - gds * vds - gm * vgs);
      break;
    }
    case "B":
      for (const st of e.at(v, dt, state)) {
        if (st.g) s.g(st.a, st.b, st.g);
        if (st.i) s.i(st.a, st.b, st.i);
      }
      break;
  }
}

function diode(vd, is, nvt) {
  if (vd < -5 * nvt) return [-is + GMIN * vd, GMIN];
  const ex = Math.exp(vd / nvt);
  return [is * (ex - 1), (is / nvt) * ex + GMIN];
}

function gauss(A, z) {
  const n = z.length;
  for (let c = 0; c < n; c++) {
    let p = c;
    for (let r = c + 1; r < n; r++) if (Math.abs(A[r][c]) > Math.abs(A[p][c])) p = r;
    if (Math.abs(A[p][c]) < 1e-30) return null;
    if (p !== c) { [A[c], A[p]] = [A[p], A[c]]; [z[c], z[p]] = [z[p], z[c]]; }
    const pivot = A[c][c];
    for (let r = c + 1; r < n; r++) {
      const f = A[r][c] / pivot;
      if (!f) continue;
      const Ar = A[r], Ac = A[c];
      for (let k = c; k < n; k++) Ar[k] -= f * Ac[k];
      z[r] -= f * z[c];
    }
  }
  const x = new Float64Array(n);
  for (let r = n - 1; r >= 0; r--) {
    let t = z[r];
    for (let k = r + 1; k < n; k++) t -= A[r][k] * x[k];
    x[r] = t / A[r][r];
  }
  return x;
}

// Current through each element: R/C/D a → b (or a → k), V out of +, NPN into the collector, NMOS d → s.
function currents(circuit, v, dt, state) {
  return circuit.elements.map((e) => {
    switch (e.kind) {
      case "R": return (v[e.a] - v[e.b]) / e.r;
      case "C": return dt > 0 ? (e.c / dt) * (v[e.a] - v[e.b] - (state[e.key] ?? 0)) : 0;
      case "V": return (e.v - (v[e.p] - v[e.n])) / e.r;
      case "D": return diode(Math.min(v[e.a] - v[e.k], 2.5), e.is, e.n * VT)[0];
      case "NPN": {
        const vbe = Math.min(v[e.b] - v[e.e], 0.95), vbc = Math.min(v[e.b] - v[e.c], 0.95);
        return e.is * (Math.exp(vbe / VT) - Math.exp(vbc / VT)) - (e.is / e.br) * (Math.exp(vbc / VT) - 1);
      }
      case "NMOS": {
        const vgs = v[e.g] - v[e.s], vds = v[e.d] - v[e.s], vov = vgs - e.vth;
        if (vov <= 0) return 0;
        return vds < vov ? e.kp * (vov * vds - vds * vds / 2) : (e.kp / 2) * vov * vov;
      }
      default: return 0;
    }
  });
}
