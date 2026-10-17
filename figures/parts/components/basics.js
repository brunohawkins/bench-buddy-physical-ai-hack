// Basic through-hole parts. Each comes apart to show what is inside.
// Every leaded part reports its pins ({ x, y, name } where each leg ends, at z = tip) and how deep
// those legs sit in a breadboard (insert), and takes options that move its legs onto the 2.54 mm grid.
const GRID = 2.54;
import * as THREE from "three";
import { model, at, bandsOf, ohmsText } from "../kit.js";

// Axial leads: out of the body ends along x, bent 90° down at ±pitch/2, ending at z = -legs.
function axialLeads(k, target, end, z, pitch, r, legs = 9) {
  for (const s of [-1, 1]) {
    const x = (s * pitch) / 2;
    k.tube(target, [[s * end, 0, z], [x - s * 0.9, 0, z], [x, 0, z - 0.9], [x, 0, -legs]], r, "tin", { segments: 40, radial: 10 });
  }
}

export function resistor({ ohms = 1000, span = 4, legs = 9 } = {}) {
  const pitch = span * GRID;
  const k = model(`Resistor ${ohmsText(ohms)}`, [
    { name: "Core and leads", offset: [0, 0, 0], delay: 0 },
    { name: "Coating", offset: [0, 7, 0], delay: 0.05 },
  ]);
  const z = 1.8, L = 6.3, x0 = -L / 2;
  const alongX = [1, 0, 0];
  const core = k.part(0, "Ceramic core", "Alumina rod the resistive film is deposited on");
  k.rod(core, [x0 + 0.5, 0, z], [x0 + L - 0.5, 0, z], 0.8, "white");
  const film = k.part(0, "Metal-film spiral", "A helix cut into the film by laser; its length sets the value");
  const helix = [];
  for (let i = 0; i <= 160; i++) { const t = i / 160, a = t * Math.PI * 2 * 9; helix.push([x0 + 1.1 + t * (L - 2.2), Math.sin(a) * 0.83, z + Math.cos(a) * 0.83]); }
  k.tube(film, helix, 0.07, "copper", { segments: 400, radial: 6 });
  const caps = k.part(0, "End caps", "Pressed steel caps that join the film to the leads");
  k.rod(caps, [x0 + 0.1, 0, z], [x0 + 1.1, 0, z], 1.15, "steel");
  k.rod(caps, [x0 + L - 1.1, 0, z], [x0 + L - 0.1, 0, z], 1.15, "steel");
  const leads = k.part(0, "Leads", `Tinned copper wire · 0.6 mm, bent to span ${span} holes (${pitch.toFixed(2)} mm)`);
  axialLeads(k, leads, L / 2 - 0.2, z, pitch, 0.3, legs);
  const coat = k.part(1, "Epoxy coating", "Insulating lacquer over the film, printed with the colour code");
  const profile = [[0, 0], [1.0, 0.05], [1.27, 0.4], [1.27, 1.6], [1.07, 2.05], [1.07, 4.25], [1.27, 4.7], [1.27, 5.9], [1.0, 6.25], [0, 6.3]];
  k.lathe(coat, profile, [x0, 0, z], alongX, "resistorBody");
  const bands = k.part(1, `Colour bands · ${ohmsText(ohms)}`, "Digit, digit, multiplier, tolerance: read from the end nearest a band");
  const radiusAt = (s) => { for (let i = 1; i < profile.length; i++) if (s <= profile[i][1]) { const [r0, s0] = profile[i - 1], [r1, s1] = profile[i]; return r0 + ((r1 - r0) * (s - s0)) / (s1 - s0); } return 0; };
  [...bandsOf(ohms), "bandGold"].forEach((m, i) => {
    const s = [0.95, 2.35, 3.15, 5.25][i], w = i === 3 ? 0.55 : 0.5;
    const r = Math.max(radiusAt(s - w / 2), radiusAt(s + w / 2)) + 0.03;
    k.rod(bands, [x0 + s - w / 2, 0, z], [x0 + s + w / 2, 0, z], r, m, { segments: 32 });
  });
  return k.done({ spec: `${ohmsText(ohms)} ±5% · ¼ W metal film`, pins: [{ x: -pitch / 2, y: 0, name: "1" }, { x: pitch / 2, y: 0, name: "2" }], tip: -legs, insert: 5.5, spans: [3, 8] });
}

// Three-digit ceramic code: 100 nF → "104" (10 × 10⁴ pF).
const capCode = (nf) => { const pf = Math.round(nf * 1000), e = Math.floor(Math.log10(pf)) - 1; return `${Math.round(pf / 10 ** e)}${e}`; };

export function ceramicCap({ span = 2, legs = 8, nf = 100 } = {}) {
  const code = capCode(nf), value = nf >= 1000 ? `${nf / 1000} µF` : `${nf} nF`;
  const half = (span * GRID) / 2;
  const k = model(`Ceramic capacitor ${value}`, [
    { name: "Dielectric and leads", offset: [0, 0, 0], delay: 0 },
    { name: "Coating", offset: [0, 9, 0], delay: 0.05 },
  ]);
  const zc = 4.2;
  const disc = k.part(0, "Ceramic dielectric", `Barium titanate disc · high permittivity, so a tiny disc stores ${value}`);
  k.rod(disc, [0, -0.35, zc], [0, 0.35, zc], 2.0, "white", { segments: 40 });
  const plates = k.part(0, "Silver electrodes", "Fired-on silver on both faces of the disc");
  k.rod(plates, [0, -0.45, zc], [0, -0.35, zc], 1.8, "steel", { segments: 40 });
  k.rod(plates, [0, 0.35, zc], [0, 0.45, zc], 1.8, "steel", { segments: 40 });
  const leads = k.part(0, "Leads", `Tinned wire · ${(span * GRID).toFixed(2)} mm pitch, kinked to sit off the board`);
  for (const s of [-1, 1]) k.tube(leads, [[s * 1.0, s * 0.5, zc], [s * 1.6, s * 0.5, zc - 2.3], [s * half, 0, zc - 3.6], [s * half, 0, zc - 4.6], [s * half, 0, -legs]], 0.25, "tin", { segments: 40, radial: 8 });
  const coat = k.part(1, "Epoxy dip coating", `Marked ${code} = ${code.slice(0, 2)} × 10^${code[2]} pF = ${value}`);
  const shell = k.mesh(coat, new THREE.SphereGeometry(2.6, 40, 24), "ceramic");
  shell.scale.set(1, 1, 0.48);
  shell.position.copy(at(0, 0, zc));
  k.label(coat, 0, -1.25, zc, 3, 1.4, [[code, 1]], { color: "#3a2a10", face: "front", weight: 700 });
  return k.done({ spec: `${value} (${code}) · 50 V ceramic disc`, pins: [{ x: -half, y: 0, name: "1" }, { x: half, y: 0, name: "2" }], tip: -legs, insert: 5.5, spans: [1, 3] });
}

export function electrolytic({ legs = 8, uf = 100, volts = 16 } = {}) {
  const k = model(`Electrolytic capacitor ${uf} µF`, [
    { name: "Winding and seal", offset: [0, 0, 0], delay: 0.08 },
    { name: "Aluminium can", offset: [0, 13, 0], delay: 0.04 },
    { name: "Sleeve", offset: [0, 26, 0], delay: 0 },
  ]);
  const R = 3.15, H = 11, up = [0, 0, 1];
  const roll = k.part(0, "Foil winding", "Etched aluminium anode foil, paper separator and cathode foil rolled up, soaked in electrolyte");
  k.rod(roll, [0, 0, 1.6], [0, 0, H - 1.2], 2.75, "foam", { segments: 40 });
  const spiral = [];
  for (let i = 0; i <= 120; i++) { const t = i / 120, a = t * Math.PI * 2 * 5, r = 0.4 + t * 2.35; spiral.push([Math.cos(a) * r, Math.sin(a) * r, H - 1.19]); }
  k.tube(roll, spiral, 0.05, "aluminium", { segments: 300, radial: 4 });
  const seal = k.part(0, "Rubber bung", "Seals the can; the leads pass through it");
  k.rod(seal, [0, 0, 0.3], [0, 0, 1.6], 2.95, "rubber", { segments: 40 });
  const leads = k.part(0, "Leads", "+ is the longer lead · 2.54 mm pitch");
  k.rod(leads, [1.27, 0, 0.3], [1.27, 0, -legs - 2], 0.25, "tin");
  k.rod(leads, [-1.27, 0, 0.3], [-1.27, 0, -legs], 0.25, "tin");
  k.rod(leads, [1.27, 0, 1.6], [1.27, 0, 3], 0.2, "aluminium");
  k.rod(leads, [-1.27, 0, 1.6], [-1.27, 0, 3], 0.2, "aluminium");
  const can = k.part(1, "Aluminium can", "Cathode-side case with a scored vent that splits open safely if over-pressured");
  k.lathe(can, [[R - 0.05, 0], [R - 0.05, 1.0], [R - 0.35, 1.3], [R - 0.05, 1.6], [R - 0.05, H - 0.2], [R - 0.3, H], [0, H]], [0, 0, 0], up, "aluminium", 48);
  const vent = [];
  for (const a of [0, (2 * Math.PI) / 3, (4 * Math.PI) / 3]) vent.push(a);
  for (const a of vent) k.rod(can, [0, 0, H + 0.01], [Math.cos(a) * 2.1, Math.sin(a) * 2.1, H + 0.01], 0.12, "hole", { segments: 6 });
  const sleeve = k.part(2, "PVC sleeve", `Printed ${uf} µF ${volts} V; the light stripe of − signs marks the negative lead`);
  k.mesh(sleeve, new THREE.CylinderGeometry(R + 0.06, R + 0.06, H - 0.6, 48, 1, true, 0.9, Math.PI * 2 - 1.8), "sleeveBlue").position.copy(at(0, 0, 0.3 + (H - 0.6) / 2));
  const stripe = k.mesh(sleeve, new THREE.CylinderGeometry(R + 0.06, R + 0.06, H - 0.6, 16, 1, true, -0.9, 1.8), "sleeveStripe");
  stripe.position.copy(at(0, 0, 0.3 + (H - 0.6) / 2));
  stripe.rotation.y = Math.PI;
  k.lathe(sleeve, [[R + 0.06, 0], [R + 0.06, 0.3], [R - 0.6, 0.35]], [0, 0, H - 0.3], up, "sleeveBlue", 48);
  for (let i = 0; i < 4; i++) k.box(sleeve, -R - 0.12, -R - 0.06, -0.5, 0.5, 2.5 + i * 2.1, 2.8 + i * 2.1, "sleeveBlue");
  return k.done({ spec: `${uf} µF · ${volts} V · 6.3 × 11 mm radial, 105 °C`, pins: [{ x: 1.27, y: 0, name: "+" }, { x: -1.27, y: 0, name: "−" }], tip: -legs, insert: 5.5 });
}

export function led({ colour = "red", legs = 15 } = {}) {
  const k = model(`5 mm LED (${colour})`, [
    { name: "Lead frame", offset: [0, 0, 0], delay: 0.04 },
    { name: "Epoxy lens", offset: [0, 14, 0], delay: 0 },
  ]);
  const up = [0, 0, 1];
  const anvil = k.part(0, "Anvil (cathode −)", "The larger frame: a reflector cup holding the die");
  k.box(anvil, -2.0, -0.4, -0.25, 0.25, 0, 4.2, "steel");
  k.lathe(anvil, [[0.35, 0], [0.75, 0.6], [0.8, 0.65]], [-0.9, 0, 4.2], up, "steel", 24);
  const post = k.part(0, "Post (anode +)", "The smaller frame; the bond wire lands on it");
  k.box(post, 0.6, 1.6, -0.25, 0.25, 0, 4.6, "steel");
  const die = k.part(0, "LED die", "AlGaInP chip ~0.25 mm square: electrons and holes recombine and emit red light");
  k.box(die, -1.05, -0.75, -0.15, 0.15, 4.25, 4.5, "ledRed");
  const wire = k.part(0, "Bond wire", "25 µm gold wire from the top of the die to the post");
  k.tube(wire, [[-0.9, 0, 4.5], [-0.3, 0, 5.6], [0.6, 0, 5.2], [0.9, 0, 4.6]], 0.04, "gold", { segments: 30, radial: 5 });
  const leadPart = k.part(0, "Leads", "Anode is the longer lead · 2.54 mm pitch");
  k.box(leadPart, 1.27 - 0.25, 1.27 + 0.25, -0.25, 0.25, -legs - 2, 0, "tin");
  k.box(leadPart, -1.27 - 0.25, -1.27 + 0.25, -0.25, 0.25, -legs, 0, "tin");
  const lens = k.part(1, "Epoxy lens", "Tinted, diffusing dome · flat on the flange marks the cathode");
  const p = [[0, 0], [2.9, 0], [2.9, 1.0], [2.5, 1.0], [2.5, 5.6]];
  for (let i = 1; i <= 12; i++) { const a = (i / 12) * (Math.PI / 2); p.push([2.5 * Math.cos(a), 5.6 + 2.5 * Math.sin(a)]); }
  k.lathe(lens, p, [0, 0, 0], up, colour === "red" ? "epoxyRed" : "epoxyRed", 48).userData.glow = true;
  return k.done({ spec: "5 mm red LED · ~2.0 V forward, 20 mA max", pins: [{ x: 1.27, y: 0, name: "+ (anode)" }, { x: -1.27, y: 0, name: "− (cathode)" }], tip: -legs, insert: 5.5 });
}

export function to92({ part: partNo = "2N2222A", pins = ["E", "B", "C"], kind = "NPN transistor", spec = "NPN · 40 V, 600 mA · pinout E B C", legs = 10 } = {}) {
  const k = model(`${partNo} (TO-92)`, [
    { name: "Lead frame", offset: [0, 0, 0], delay: 0.04 },
    { name: "Epoxy body", offset: [0, 10, 0], delay: 0 },
  ]);
  const z0 = 3.0, h = 4.8;
  const frame = k.part(0, "Lead frame", "Stamped leads, the outer two splayed from 1.27 to 2.54 mm so they drop into breadboard holes; the die sits on the collector pad");
  pins.forEach((name, i) => {
    const x = (i - 1) * 1.27, X = (i - 1) * GRID;
    k.box(frame, x - 0.23, x + 0.23, -0.2, 0.2, z0 - 0.8, z0 + 2.2, "tin");
    if (i === 1) k.box(frame, x - 0.23, x + 0.23, -0.2, 0.2, -legs, z0 - 0.8, "tin");
    else k.tube(frame, [[x, 0, z0 - 0.8], [x, 0, z0 - 1.4], [X, 0, z0 - 3.0], [X, 0, z0 - 3.6], [X, 0, -legs]], 0.22, "tin", { segments: 30, radial: 8 });
  });
  k.box(frame, 1.27 - 0.6, 1.27 + 0.6, -0.2, 0.2, z0 + 2.2, z0 + 3.4, "tin");
  const die = k.part(0, "Silicon die", `${kind} die, ~0.5 mm square`);
  k.box(die, 1.0, 1.55, -0.32, -0.2, z0 + 2.5, z0 + 3.05, "die");
  const wires = k.part(0, "Bond wires", "Gold wires from emitter and base pads on the die to their leads");
  k.tube(wires, [[1.1, -0.3, z0 + 2.9], [0.4, -0.5, z0 + 3.6], [-0.2, -0.3, z0 + 2.4], [-1.27, -0.2, z0 + 2.1]], 0.035, "gold", { segments: 30, radial: 5 });
  k.tube(wires, [[1.3, -0.3, z0 + 2.9], [0.8, -0.45, z0 + 3.3], [0, -0.25, z0 + 2.3]], 0.035, "gold", { segments: 30, radial: 5 });
  const body = k.part(1, "Epoxy body", `TO-92 · flat face toward you, pins ${pins.join(" ")} left to right`);
  const s = new THREE.Shape();
  s.moveTo(-1.95, -1.4);
  s.lineTo(1.95, -1.4);
  s.absarc(0, 0, 2.4, -Math.asin(1.4 / 2.4), Math.PI + Math.asin(1.4 / 2.4), false);
  s.lineTo(-1.95, -1.4);
  const g = new THREE.ExtrudeGeometry(s, { depth: h, bevelEnabled: false, curveSegments: 32 });
  g.rotateX(-Math.PI / 2);
  g.translate(0, z0, 0);
  k.mesh(body, g, "black");
  k.label(body, 0, -1.4, z0 + h / 2, 3.6, 2.4, [[partNo, 1], [pins.join(" "), 0.8]], { color: "#bdbdbd", face: "front" });
  return k.done({ spec, pins: pins.map((name, i) => ({ x: (i - 1) * GRID, y: 0, name })), tip: -legs, insert: 5.5 });
}

export function to220({ part: partNo = "IRLZ44N", spec = "Logic-level N-channel MOSFET · 55 V, 47 A, 0.022 Ω at 5 V gate · pinout G D S", legs = 14 } = {}) {
  const k = model(`${partNo} (TO-220)`, [
    { name: "Tab and leads", offset: [0, 0, 0], delay: 0.04 },
    { name: "Epoxy body", offset: [0, 3, 12], delay: 0 },
  ]);
  const tab = k.part(0, "Metal tab (drain)", "Copper tab: heatsink mount and drain connection, Ø3.6 mm hole");
  // Vertical plate in the x–z plane at the back (y 3.1–4.4), z 0–15.5, with the mounting hole.
  const shape = new THREE.Shape();
  shape.moveTo(-5, 0); shape.lineTo(5, 0); shape.lineTo(5, 15.1); shape.lineTo(4.6, 15.5); shape.lineTo(-4.6, 15.5); shape.lineTo(-5, 15.1); shape.lineTo(-5, 0);
  const hole = new THREE.Path();
  hole.absarc(0, 12.6, 1.8, 0, Math.PI * 2, true);
  shape.holes.push(hole);
  const tg = new THREE.ExtrudeGeometry(shape, { depth: 1.3, bevelEnabled: false, curveSegments: 24 });
  tg.translate(0, 0, -4.4);
  k.mesh(tab, tg, "shell");
  const die = k.part(0, "MOSFET die", "Vertical power MOSFET die soldered to the tab");
  k.box(die, -1.8, 1.8, 2.9, 3.1, 4.0, 7.2, "die");
  const wires = k.part(0, "Bond wires", "Aluminium wedge bonds from gate and source pads to their leads");
  k.tube(wires, [[-1.4, 2.9, 4.4], [-2.2, 2.4, 3.2], [-2.54, 2.2, 1.6]], 0.08, "aluminium", { segments: 20, radial: 6 });
  for (const dx of [0.6, 1.2]) k.tube(wires, [[dx, 2.9, 4.4], [2.0, 2.4, 3.2], [2.54, 2.2, 1.6]], 0.12, "aluminium", { segments: 20, radial: 6 });
  const leads = k.part(0, "Leads", "G D S at 2.54 mm pitch; the middle lead is the drain, same as the tab");
  for (const x of [-2.54, 0, 2.54]) {
    k.box(leads, x - 0.75, x + 0.75, 1.9, 2.4, -2.5, 1.8, "tin");
    k.box(leads, x - 0.4, x + 0.4, 1.9, 2.4, -legs, -2.5, "tin");
  }
  const body = k.part(1, "Epoxy body", "Moulded over the die and the base of the tab");
  k.box(body, -5, 5, 0, 4.4, 0, 9.0, "black", 0.3);
  k.label(body, 0, 0, 5.2, 8.5, 4.5, [[partNo, 1], ["G   D   S", 0.75]], { color: "#bdbdbd", face: "front" });
  return k.done({ spec, pins: ["G", "D", "S"].map((name, i) => ({ x: (i - 1) * GRID, y: 2.15, name })), tip: -legs, insert: 5.5 });
}

export function diode({ glass = false, span = 4, legs = 9 } = {}) {
  const pitch = span * GRID;
  const name = glass ? "1N4148 signal diode" : "1N4007 rectifier diode";
  const k = model(name, [
    { name: "Die and leads", offset: [0, 0, 0], delay: 0.04 },
    { name: "Body", offset: [0, 7, 0], delay: 0 },
  ]);
  const L = glass ? 3.8 : 5.2, R = glass ? 0.9 : 1.35, z = R + 0.4, x0 = -L / 2;
  const die = k.part(0, "PN junction die", glass ? "Small silicon die clamped between two slugs" : "Glass-passivated silicon die, 1 A rated");
  k.box(die, -0.25, 0.25, -0.35, 0.35, z - 0.35, z + 0.35, "die");
  const slugs = k.part(0, "Contact slugs", "Dumet slugs pressing on each side of the die");
  k.rod(slugs, [x0 + 0.4, 0, z], [-0.25, 0, z], glass ? 0.35 : 0.55, "copper");
  k.rod(slugs, [0.25, 0, z], [-x0 - 0.4, 0, z], glass ? 0.35 : 0.55, "copper");
  const leads = k.part(0, "Leads", `Axial · ${glass ? "0.5" : "0.8"} mm, bent to span ${span} holes (${pitch.toFixed(2)} mm)`);
  axialLeads(k, leads, L / 2 - 0.2, z, pitch, glass ? 0.25 : 0.4, legs);
  const body = k.part(1, glass ? "Glass body (DO-35)" : "Epoxy body (DO-41)", glass ? "Hermetic glass tube; the black band is the cathode" : "Moulded epoxy; the silver band is the cathode");
  k.rod(body, [x0, 0, z], [x0 + L, 0, z], R, glass ? "glassOrange" : "black", { segments: 32 });
  k.rod(body, [x0 + L - (glass ? 0.9 : 1.1), 0, z], [x0 + L - 0.3, 0, z], R + 0.03, glass ? "black" : "bandSilver", { segments: 32 });
  return k.done({ spec: glass ? "1N4148 · 100 V, 200 mA, 4 ns fast switching" : "1N4007 · 1000 V, 1 A general-purpose rectifier", pins: [{ x: -pitch / 2, y: 0, name: "A (anode)" }, { x: pitch / 2, y: 0, name: "K (cathode, banded end)" }], tip: -legs, insert: 5.5, spans: [3, 8] });
}

export function tactile() {
  const k = model("Tactile push button 6 × 6 mm", [
    { name: "Base", offset: [0, 0, 0], delay: 0.08 },
    { name: "Dome", offset: [0, 5, 0], delay: 0.04 },
    { name: "Cover and plunger", offset: [0, 11, 0], delay: 0 },
  ]);
  const base = k.part(0, "Base and contacts", "Nylon base with four terminals: each side pair is already connected");
  k.box(base, -3, 3, -3, 3, 0, 3.4, "black", 0.2);
  k.boxes(base, [[-2.2, -1.2, -1.6, 1.6, 3.4, 3.45], [1.2, 2.2, -1.6, 1.6, 3.4, 3.45]], "steel");
  // Legs leave the body 6.5 × 4.5 mm apart and kink out to 7.62 × 5.08 mm, the breadboard grid.
  for (const sx of [-1, 1]) for (const sy of [-1, 1]) k.tube(base, [[sx * 3.25, sy * 2.25, 1.0], [sx * 3.25, sy * 2.25, 0], [sx * 3.81, sy * 2.54, -1.0], [sx * 3.81, sy * 2.54, -3.5]], 0.25, "steel", { segments: 20, radial: 6 });
  const dome = k.part(1, "Snap dome", "Stainless spring dome: it clicks through and bridges the two contacts");
  const g = new THREE.SphereGeometry(2.2, 32, 12, 0, Math.PI * 2, 0, Math.PI / 3.2);
  const m = k.mesh(dome, g, "steel");
  m.position.copy(at(0, 0, 3.45 - 2.2 * Math.cos(Math.PI / 3.2)));
  const cover = k.part(2, "Cover and plunger", "Steel cover crimped to the base · plunger travel 0.25 mm, ~160 gf");
  k.box(cover, -3, 3, -3, 3, 3.5, 3.75, "steel", 0.1);
  k.boxes(cover, [[-3.05, -2.75, -1.0, 1.0, 1.5, 3.75], [2.75, 3.05, -1.0, 1.0, 1.5, 3.75]], "steel");
  k.rod(cover, [0, 0, 3.5], [0, 0, 5.0], 1.75, "black", { segments: 32 });
  return k.done({ spec: "6 × 6 × 5 mm · 12 V 50 mA · 4-pin THT", pins: [[-1, -1, "1"], [1, -1, "2"], [-1, 1, "3"], [1, 1, "4"]].map(([sx, sy, name]) => ({ x: sx * 3.81, y: sy * 2.54, name })), tip: -3.5, insert: 3.0 });
}

export function dip8({ partNo = "NE555P", spec = "Timer IC · 4.5–16 V · DIP-8 (0.3 in)" } = {}) {
  const k = model(`${partNo} (DIP-8)`, [
    { name: "Lead frame", offset: [0, 0, 0], delay: 0.04 },
    { name: "Epoxy body", offset: [0, 10, 0], delay: 0 },
  ]);
  const zb = 0.8, zt = 4.1;
  const frame = k.part(0, "Lead frame", "Eight leads at 2.54 mm pitch, rows 7.62 mm apart; the die sits on the centre paddle");
  const list = [];
  for (let i = 0; i < 4; i++) for (const sy of [-1, 1]) {
    const x = -3.81 + i * 2.54;
    list.push([x - 0.75, x + 0.75, sy * 3.2 - 0.13, sy * 3.2 + 0.13, zb + 0.8, zb + 1.06]);
    list.push([x - 0.75, x + 0.75, sy * 3.81 - 0.13, sy * 3.81 + 0.13, -0.2, zb + 1.06]);
    list.push([x - 0.25, x + 0.25, sy * 3.81 - 0.13, sy * 3.81 + 0.13, -3.4, -0.2]);
    list.push([x * 0.6 - 0.25, x * 0.6 + 0.25, sy > 0 ? 1.7 : -3.2, sy > 0 ? 3.2 : -1.7, zb + 0.8, zb + 1.06]);
  }
  k.boxes(frame, list, "tin");
  k.box(frame, -1.5, 1.5, -1.5, 1.5, zb + 0.8, zb + 1.06, "tin");
  const die = k.part(0, "Silicon die", "Bipolar 555 die: two comparators, a flip-flop and a discharge transistor");
  k.box(die, -1.0, 1.0, -0.9, 0.9, zb + 1.06, zb + 1.36, "die");
  const wires = k.part(0, "Bond wires", "Gold wire from each pad on the die to its lead finger");
  for (let i = 0; i < 4; i++) for (const sy of [-1, 1]) {
    const x = -3.81 + i * 2.54;
    k.tube(wires, [[x * 0.22, sy * 0.75, zb + 1.36], [x * 0.6, sy * 1.6, zb + 2.0], [x * 0.8, sy * 2.2, zb + 1.06]], 0.03, "gold", { segments: 16, radial: 4 });
  }
  const body = k.part(1, "Epoxy body", "The notch and dot mark pin 1; pins count anticlockwise seen from above");
  k.box(body, -4.8, 4.8, -3.2, 3.2, zb, zt, "chip", 0.35);
  k.box(body, -4.82, -4.3, -0.6, 0.6, zt - 0.3, zt + 0.001, "hole", 0.1);
  k.ring(body, -3.6, -2.2, zt + 0.005, 0, 0.35, "hole");
  k.label(body, 0.3, 0, zt, 7.5, 3.2, [[partNo, 1], ["TI 2347", 0.7]], { color: "#9a9a9e" });
  // Pin 1 is front-left by the notch; pins count anticlockwise seen from above.
  const pins = [];
  for (let i = 0; i < 4; i++) pins.push({ x: -3.81 + i * GRID, y: -3.81, name: String(i + 1) });
  for (let i = 0; i < 4; i++) pins.push({ x: 3.81 - i * GRID, y: 3.81, name: String(i + 5) });
  return k.done({ spec, pins, tip: -3.4, insert: 3.0 });
}
