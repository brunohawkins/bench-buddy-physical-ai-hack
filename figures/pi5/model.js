// Raspberry Pi 5 (4 GB) as a three.js scene graph, built from the official mechanical drawing
// (datasheets.raspberrypi.com/rpi5/raspberry-pi-5-mechanical-drawing.pdf). Units are millimetres.
// Runs in the browser (viewer) and in Node (GLB export). Pi coordinates: x along the 85 mm edge,
// y along the 56 mm edge with the HDMI edge at y = 0, z up from the board's top face.
import * as THREE from "three";
import { RoundedBoxGeometry } from "three/addons/geometries/RoundedBoxGeometry.js";
import { mergeGeometries } from "three/addons/utils/BufferGeometryUtils.js";

const T = 1.6; // board thickness
const at = (x, y, z) => new THREE.Vector3(x - 42.5, z, 28 - y);

export const ASSEMBLIES = [
  { name: "Board", offset: [0, 0, 0], delay: 0 },
  { name: "Silicon", offset: [0, 15, 0], delay: 0.1 },
  { name: "Lids and shields", offset: [0, 30, 0], delay: 0 },
  { name: "USB and Ethernet", offset: [24, 4, 0], delay: 0.16 },
  { name: "Power and HDMI", offset: [0, 3, 20], delay: 0.2 },
  { name: "Headers", offset: [0, 22, -6], delay: 0.06 },
  { name: "Ribbon connectors", offset: [0, 18, 0], delay: 0.24 },
  { name: "Underside", offset: [0, -14, 0], delay: 0.12 },
];

const MATERIALS = {
  pcb: { color: 0x1f6e43, roughness: 0.75, metalness: 0 },
  mask: { color: 0x2a8a55, roughness: 0.7, metalness: 0 },
  gold: { color: 0xd4aa4f, roughness: 0.35, metalness: 0.85 },
  tin: { color: 0xc9cdd1, roughness: 0.4, metalness: 0.8 },
  nickel: { color: 0xc4c7cb, roughness: 0.3, metalness: 0.9 },
  shell: { color: 0xb8bcc1, roughness: 0.38, metalness: 0.85 },
  black: { color: 0x1b1b1d, roughness: 0.55, metalness: 0 },
  chip: { color: 0x141416, roughness: 0.45, metalness: 0.05 },
  hole: { color: 0x050505, roughness: 0.9, metalness: 0 },
  blue: { color: 0x2f5bd8, roughness: 0.5, metalness: 0 },
  substrate: { color: 0x3b4a32, roughness: 0.6, metalness: 0 },
  die: { color: 0x2a3150, roughness: 0.25, metalness: 0.4 },
  latch: { color: 0xd9d0b8, roughness: 0.6, metalness: 0 },
  jst: { color: 0xeeeae2, roughness: 0.6, metalness: 0 },
  cap: { color: 0xb08a58, roughness: 0.6, metalness: 0 },
  ledGreen: { color: 0x3ccf72, roughness: 0.3, metalness: 0, emissive: 0x1a6a38 },
  ledRed: { color: 0xff4d4d, roughness: 0.3, metalness: 0, emissive: 0x7a1a1a },
  ledAmber: { color: 0xf0a020, roughness: 0.3, metalness: 0, emissive: 0x6a4a10 },
  silk: { color: 0xf2f2ee, roughness: 0.8, metalness: 0 },
  sd: { color: 0x2b2b2e, roughness: 0.5, metalness: 0 },
};

export function buildPi5({ labels = typeof document !== "undefined" } = {}) {
  const mats = Object.fromEntries(Object.entries(MATERIALS).map(([name, m]) => {
    const mat = new THREE.MeshStandardMaterial({ ...m, flatShading: false });
    mat.name = name;
    return [name, mat];
  }));
  const root = new THREE.Group();
  root.name = "Raspberry Pi 5 (4 GB)";
  const groups = ASSEMBLIES.map((a) => {
    const g = new THREE.Group();
    g.name = a.name;
    g.userData.offset = a.offset;
    root.add(g);
    return g;
  });
  const parts = [];

  // A part is a named group of meshes that highlights and reports as one.
  function part(assembly, name, spec) {
    const g = new THREE.Group();
    g.name = name;
    g.userData = { part: parts.length, name, spec, assembly };
    groups[assembly].add(g);
    parts.push(g);
    return g;
  }
  function mesh(target, geometry, mat, name) {
    const m = new THREE.Mesh(geometry, mats[mat]);
    if (name) m.name = name;
    target.add(m);
    return m;
  }
  // An axis-aligned box from Pi ranges, optionally rounded.
  function box(target, x0, x1, y0, y1, z0, z1, mat, r = 0) {
    const w = x1 - x0, h = z1 - z0, d = y1 - y0;
    const radius = Math.min(r, Math.min(w, h, d) / 2 - 0.01);
    const geometry = radius > 0.02 ? new RoundedBoxGeometry(w, h, d, 2, radius) : new THREE.BoxGeometry(w, h, d);
    const m = mesh(target, geometry, mat);
    m.position.copy(at((x0 + x1) / 2, (y0 + y1) / 2, (z0 + z1) / 2));
    return m;
  }
  // Many small boxes merged into one mesh (pins, capacitors).
  function boxes(target, list, mat) {
    const geos = list.map(([x0, x1, y0, y1, z0, z1]) => {
      const g = new THREE.BoxGeometry(x1 - x0, z1 - z0, y1 - y0);
      const c = at((x0 + x1) / 2, (y0 + y1) / 2, (z0 + z1) / 2);
      g.translate(c.x, c.y, c.z);
      return g;
    });
    return mesh(target, mergeGeometries(geos), mat);
  }
  function cylinder(target, x, y, z0, z1, r, mat, segments = 32) {
    const m = mesh(target, new THREE.CylinderGeometry(r, r, z1 - z0, segments), mat);
    m.position.copy(at(x, y, (z0 + z1) / 2));
    return m;
  }
  function ring(target, x, y, z, r0, r1, mat) {
    const m = mesh(target, new THREE.RingGeometry(r0, r1, 40), mat);
    m.rotation.x = z >= 0 ? -Math.PI / 2 : Math.PI / 2;
    m.position.copy(at(x, y, z));
    return m;
  }
  // Text printed on a top face: a canvas texture on a plane (browser only).
  function label(target, x, y, z, w, h, lines, { color = "#d8d8d8", font = "600 64px ui-monospace, Menlo, Consolas, monospace", rotate = 0 } = {}) {
    if (!labels) return;
    const canvas = document.createElement("canvas");
    canvas.width = 1024;
    canvas.height = Math.max(16, Math.round((1024 * h) / w));
    const ctx = canvas.getContext("2d");
    ctx.fillStyle = color;
    ctx.textAlign = "center";
    ctx.textBaseline = "middle";
    lines.forEach((line, i) => {
      const [text, scale = 1] = Array.isArray(line) ? line : [line];
      // Fit each line to its row height, then shrink it until it fits the width.
      let px = (canvas.height / lines.length) * 0.78 * scale;
      ctx.font = font.replace(/\d+px/, `${px}px`);
      const wide = ctx.measureText(text).width;
      if (wide > canvas.width * 0.96) { px *= (canvas.width * 0.96) / wide; ctx.font = font.replace(/\d+px/, `${px}px`); }
      ctx.fillText(text, canvas.width / 2, (canvas.height * (i + 0.5)) / lines.length);
    });
    const tex = new THREE.CanvasTexture(canvas);
    tex.anisotropy = 8;
    tex.colorSpace = THREE.SRGBColorSpace;
    const m = new THREE.Mesh(new THREE.PlaneGeometry(w, h), new THREE.MeshBasicMaterial({ map: tex, transparent: true, depthWrite: false }));
    m.rotation.x = -Math.PI / 2;
    m.rotation.z = rotate;
    m.position.copy(at(x, y, z + 0.02));
    m.userData.label = true;
    target.add(m);
  }

  // ── Board ──────────────────────────────────────────────────────────────────────────────
  const HOLES = [[3.5, 3.5, 1.35], [61.5, 3.5, 1.35], [3.5, 52.5, 1.35], [61.5, 52.5, 1.35]];
  const COOLER = [[60.9, 46.6, 1.5], [3.0, 9.3, 1.5]];
  {
    const pcb = part(0, "Printed circuit board", "85 × 56 mm · 1.6 mm FR-4, M2.5 holes on a 58 × 49 mm pattern");
    const shape = new THREE.Shape();
    const r = 3;
    shape.moveTo(r, 0);
    shape.lineTo(85 - r, 0); shape.absarc(85 - r, r, r, -Math.PI / 2, 0);
    shape.lineTo(85, 56 - r); shape.absarc(85 - r, 56 - r, r, 0, Math.PI / 2);
    shape.lineTo(r, 56); shape.absarc(r, 56 - r, r, Math.PI / 2, Math.PI);
    shape.lineTo(0, r); shape.absarc(r, r, r, Math.PI, Math.PI * 1.5);
    for (const [x, y, hr] of [...HOLES, ...COOLER]) {
      const hole = new THREE.Path();
      hole.absarc(x, y, hr, 0, Math.PI * 2, true);
      shape.holes.push(hole);
    }
    const geo = new THREE.ExtrudeGeometry(shape, { depth: T, bevelEnabled: false, curveSegments: 24 });
    geo.rotateX(-Math.PI / 2);
    geo.translate(-42.5, -T, 28);
    mesh(pcb, geo, "pcb", "PCB");
    for (const [x, y, hr] of [...HOLES, ...COOLER]) {
      ring(pcb, x, y, 0.01, hr, hr + (hr > 1.4 ? 1.0 : 1.6), "gold");
      ring(pcb, x, y, -T - 0.01, hr, hr + 1.6, "gold");
    }
    label(pcb, 33, 47.2, 0, 18, 2.4, ["Raspberry Pi 5"], { color: "#f2f2ee", font: "700 150px ui-sans-serif, system-ui, sans-serif" });
    label(pcb, 33, 45.6, 0, 16, 1.1, ["© Raspberry Pi Ltd 2023"], { color: "#d6e6da", font: "500 70px ui-sans-serif, system-ui, sans-serif" });
    label(pcb, 25.8, 8.6, 0, 6, 1.3, ["HDMI0"], { color: "#e8f0ea" });
    label(pcb, 39.2, 8.6, 0, 6, 1.3, ["HDMI1"], { color: "#e8f0ea" });
    label(pcb, 32.7, 7.3, 0, 5, 1.2, ["UART"], { color: "#e8f0ea" });
    label(pcb, 51, 24.6, 0, 10, 1.3, ["CAM/DISP 0   1"], { color: "#e8f0ea" });
    label(pcb, 61.4, 13.7, 0, 5, 1.2, ["PoE"], { color: "#e8f0ea" });
    label(pcb, 67.2, 50, 0, 4, 1.1, ["FAN"], { color: "#e8f0ea" });
    label(pcb, 5.6, 29.3, 0, 10, 1.3, ["PCIe"], { color: "#e8f0ea", rotate: Math.PI / 2 });
    // Pin-1 square pad by the GPIO.
    box(pcb, 6.2, 7.6, 50.4, 51.6, 0, 0.03, "gold");
  }

  // Passives on the top side: decoupling around the SoC, RAM and RP1; the PMIC's inductors.
  {
    const caps = part(0, "Decoupling capacitors", "0402 and 0201 MLCCs on every supply pin");
    const list = [];
    const cap = (x, y, along = "x") => list.push(along === "x" ? [x, x + 1.0, y, y + 0.5, 0, 0.5] : [x, x + 0.5, y, y + 1.0, 0, 0.5]);
    for (let x = 24.6; x <= 40.4; x += 1.8) cap(x, 13.8);
    for (let y = 16; y <= 30.5; y += 2.2) cap(42.2, y, "y");
    for (let y = 16; y <= 30.5; y += 2.6) cap(22.6, y, "y");
    for (let x = 26; x <= 39.5; x += 2.4) cap(x, 45.2);
    for (let x = 52.4; x <= 63.4; x += 2.2) cap(x, 42.6);
    for (let y = 30; y <= 40.5; y += 2.6) cap(50.6, y, "y");
    for (const [x, y] of [[4.6, 16.4], [16.4, 16.4], [4.6, 13], [16.4, 13]]) cap(x, y);
    boxes(caps, list, "cap");
    // Tinned terminations at both ends.
    boxes(caps, list.flatMap(([x0, x1, y0, y1, z0, z1]) => x1 - x0 > y1 - y0
      ? [[x0 - 0.02, x0 + 0.2, y0 - 0.02, y1 + 0.02, z0, z1 + 0.02], [x1 - 0.2, x1 + 0.02, y0 - 0.02, y1 + 0.02, z0, z1 + 0.02]]
      : [[x0 - 0.02, x1 + 0.02, y0 - 0.02, y0 + 0.2, z0, z1 + 0.02], [x0 - 0.02, x1 + 0.02, y1 - 0.2, y1 + 0.02, z0, z1 + 0.02]]), "tin");
  }
  {
    const ind = part(0, "Power inductors", "Storage for the PMIC's buck converters");
    for (const [x0, x1, y0, y1] of [[5.5, 8.0, 20.7, 23.2], [9.1, 11.6, 20.7, 23.2], [7.3, 9.0, 8.0, 10.9], [10.5, 12.0, 8.0, 10.9], [13.4, 15.0, 8.0, 10.9]]) box(ind, x0, x1, y0, y1, 0, 1.2, "black", 0.25);
  }
  {
    const btn = part(0, "Power button", "Soft power on/off, a first on a Raspberry Pi");
    box(btn, -0.9, 2.2, 16.8, 20.0, 0, 1.6, "shell", 0.2);
    box(btn, -1.5, -0.9, 17.6, 19.2, 0.35, 1.25, "black", 0.15);
  }
  {
    const leds = part(0, "Status LEDs", "Red power · green activity");
    box(leds, 0.4, 1.8, 11.8, 12.8, 0, 0.6, "ledRed", 0.1);
    box(leds, 0.4, 1.8, 13.3, 14.3, 0, 0.6, "ledGreen", 0.1);
  }

  // ── Silicon ────────────────────────────────────────────────────────────────────────────
  {
    const soc = part(1, "BCM2712 package", "Flip-chip BGA · 4× Cortex-A76 @ 2.4 GHz, VideoCore VII");
    box(soc, 24.3, 41.4, 15.2, 31.4, 0, 1.0, "substrate", 0.4);
    const balls = [];
    for (let i = 0; i < 14; i++) for (const y of [15.6, 31.0]) balls.push([24.9 + i * 1.18, 25.2 + i * 1.18, y - 0.15, y + 0.15, 1.0, 1.08]);
    boxes(soc, balls, "gold");
    const die = part(1, "BCM2712 die", "16 nm silicon, under the heat spreader");
    box(die, 28.4, 37.3, 18.9, 27.7, 1.0, 1.55, "die", 0.05);
  }
  {
    const ram = part(1, "LPDDR4X SDRAM · 4 GB", "Micron LPDDR4X-4267 · 4 GB, one package");
    box(ram, 25.7, 40.2, 33.9, 44.1, 0, 1.0, "chip", 0.25);
    label(ram, 32.95, 39, 1.0, 12, 7, [["Micron", 0.9], ["LPDDR4X", 1.1], ["4GB", 1.1]], { color: "#9a9a9e" });
  }
  {
    const rp1 = part(1, "RP1 I/O controller", "Raspberry Pi's own southbridge: USB, Ethernet MAC, MIPI, GPIO over PCIe 2.0 ×4");
    box(rp1, 52.0, 64.1, 29.3, 41.6, 0, 1.0, "chip", 0.3);
    label(rp1, 58.05, 35.45, 1.0, 9, 6, [["RP1", 1.6], ["RASPBERRY PI", 0.6]], { color: "#9a9a9e" });
  }
  {
    const phy = part(1, "BCM54213PE", "Gigabit Ethernet PHY");
    const m = box(phy, 60.2, 66.6, 20.3, 26.7, 0, 0.85, "chip", 0.2);
    m.rotation.y = Math.PI / 4;
  }
  {
    const pmic = part(1, "DA9091 PMIC", "Power management: 8 switch-mode rails and the real-time clock");
    box(pmic, 7.7, 14.5, 11.6, 18.2, 0, 0.9, "chip", 0.2);
    label(pmic, 11.1, 14.9, 0.9, 5.5, 3, [["DA9091", 1.1]], { color: "#9a9a9e" });
  }
  {
    const wifi = part(1, "CYW43455", "Dual-band 802.11ac Wi-Fi + Bluetooth 5.0");
    box(wifi, 8.0, 13.3, 40.5, 47.5, 0, 0.8, "chip", 0.2);
  }

  // ── Lids and shields ───────────────────────────────────────────────────────────────────
  {
    const lid = part(2, "Heat spreader", "Nickel-plated lid bonded over the BCM2712 die");
    box(lid, 26.0, 39.7, 16.9, 29.7, 1.0, 2.5, "nickel", 0.7);
    label(lid, 32.85, 23.3, 2.5, 11, 7, [["BROADCOM", 1.0], ["BCM2712", 1.15], ["C1", 0.8]], { color: "#55585c" });
  }
  {
    const can = part(2, "RF shield can", "Stamped steel over the wireless module, with the antenna beside it");
    box(can, 6.8, 14.5, 38.9, 49.1, 0, 1.7, "shell", 0.4);
  }

  // ── USB and Ethernet ───────────────────────────────────────────────────────────────────
  function usb(cy, tongue, name, spec) {
    const p = part(3, name, spec);
    const y0 = cy - 6.55, y1 = cy + 6.55, x0 = 70.2, x1 = 88.4;
    box(p, x0, x1, y0, y1, 0, 15.9, "shell", 0.5);
    for (const z0 of [1.4, 9.0]) {
      box(p, x1 - 0.4, x1 + 0.05, y0 + 0.8, y1 - 0.8, z0, z0 + 5.3, "hole", 0.3);
      box(p, x1 - 0.3, x1 + 0.08, y0 + 2.0, y1 - 2.0, z0 + 2.6, z0 + 4.4, tongue, 0.15);
    }
    // Ground tabs on the top and through-hole legs underneath.
    boxes(p, [[80, 86, y0 + 2.5, y0 + 3.3, 15.9, 16.05], [80, 86, y1 - 3.3, y1 - 2.5, 15.9, 16.05]], "shell");
    boxes(p, [[72, 72.8, y0 + 0.4, y0 + 1.0, -T - 2.4, 0], [72, 72.8, y1 - 1.0, y1 - 0.4, -T - 2.4, 0]], "tin");
  }
  usb(47.0, "black", "USB 2.0 ports", "2× USB-A · 480 Mb/s each");
  usb(29.1, "blue", "USB 3.0 ports", "2× USB-A · 5 Gb/s each, blue tongues");
  {
    const eth = part(3, "Gigabit Ethernet jack", "RJ45 with magnetics and link LEDs · PoE+ capable via the HAT");
    const x0 = 66.6, x1 = 88.4, y0 = 2.25, y1 = 18.15, c = 10.2;
    box(eth, x0, x1, y0, y1, 0, 13.6, "shell", 0.5);
    box(eth, x1 - 0.5, x1 + 0.05, c - 5.85, c + 5.85, 3.2, 10.6, "hole", 0.2);
    box(eth, x1 - 0.5, x1 + 0.05, c - 2.6, c + 2.6, 1.4, 3.3, "hole", 0.1);
    const contacts = [];
    for (let i = 0; i < 8; i++) contacts.push([x1 - 0.45, x1 - 0.35, c - 3.57 + i * 1.02 - 0.2, c - 3.57 + i * 1.02 + 0.2, 8.6, 10.5]);
    boxes(eth, contacts, "gold");
    box(eth, x1 - 0.2, x1 + 0.1, y0 + 0.8, y0 + 2.8, 11.2, 12.6, "ledGreen", 0.1);
    box(eth, x1 - 0.2, x1 + 0.1, y1 - 2.8, y1 - 0.8, 11.2, 12.6, "ledAmber", 0.1);
  }

  // ── Power and HDMI ─────────────────────────────────────────────────────────────────────
  {
    const usbc = part(4, "USB-C power input", "5 V ⎓ 5 A with USB PD (27 W supply)");
    box(usbc, 6.6, 15.9, -1.3, 5.9, 0, 3.2, "shell", 1.4);
    box(usbc, 7.5, 15.0, -1.38, -0.9, 0.55, 2.65, "hole", 0.95);
    box(usbc, 9.0, 13.5, -1.42, -1.0, 1.4, 1.8, "black", 0.15);
  }
  for (const [c, name, spec] of [[25.8, "micro-HDMI 0", "HDMI 2.0 · 4Kp60"], [39.2, "micro-HDMI 1", "HDMI 2.0 · 4Kp60, dual-display with HDMI 0"]]) {
    const p = part(4, name, spec);
    box(p, c - 3.3, c + 3.3, -1.5, 6.0, 0, 3.4, "shell", 0.4);
    box(p, c - 2.8, c + 2.8, -1.58, -1.1, 0.6, 2.7, "hole", 0.3);
    box(p, c - 2.0, c + 2.0, -1.62, -1.2, 1.45, 1.85, "black", 0.1);
  }

  // ── Headers ────────────────────────────────────────────────────────────────────────────
  function header(cols, rows, cx, cy, name, spec) {
    const p = part(5, name, spec);
    const pitch = 2.54;
    const x0 = cx - (cols * pitch) / 2, y0 = cy - (rows * pitch) / 2;
    box(p, x0, x0 + cols * pitch, y0, y0 + rows * pitch, 0, 2.5, "black", 0.15);
    const pins = [];
    for (let i = 0; i < cols; i++) for (let j = 0; j < rows; j++) {
      const x = x0 + (i + 0.5) * pitch, y = y0 + (j + 0.5) * pitch;
      pins.push([x - 0.32, x + 0.32, y - 0.32, y + 0.32, 2.5, 8.5]);
      pins.push([x - 0.32, x + 0.32, y - 0.32, y + 0.32, -T - 3.0, 0]);
    }
    boxes(p, pins, "gold");
  }
  header(20, 2, 32.5, 52.5, "40-pin GPIO header", "2.54 mm pitch · 3.3 V logic, driven by RP1");
  header(2, 2, 61.35, 9.55, "PoE+ header", "4 pins · power from the PoE+ HAT");
  function jst(x0, x1, y0, y1, pins, name, spec, vertical = true) {
    const p = part(5, name, spec);
    box(p, x0, x1, y0, y1, 0, 4.25, "jst", 0.15);
    const n = pins, list = [];
    for (let i = 0; i < n; i++) {
      const t = (i + 0.5) / n;
      if (vertical) list.push([x0 + 0.6, x1 - 0.6, y0 + t * (y1 - y0) - 0.15, y0 + t * (y1 - y0) + 0.15, 4.0, 4.3]);
      else list.push([x0 + t * (x1 - x0) - 0.15, x0 + t * (x1 - x0) + 0.15, y0 + 0.6, y1 - 0.6, 4.0, 4.3]);
    }
    box(p, x0 + 0.4, x1 - 0.4, y0 + 0.4, y1 - 0.4, 4.0, 4.3, "hole", 0.1);
    boxes(p, list, "tin");
  }
  jst(65.7, 68.6, 51.4, 55.5, 4, "Fan connector", "4-pin JST-SH · PWM fan for the Active Cooler");
  jst(30.2, 35.2, 2.3, 5.9, 3, "UART debug connector", "3-pin JST-SH · serial console", false);
  jst(17.3, 20.9, 3.0, 6.1, 2, "RTC battery connector", "2-pin JST-SH · keeps the real-time clock running", false);

  // ── Ribbon connectors ──────────────────────────────────────────────────────────────────
  function ffc(x0, x1, y0, y1, name, spec, teeth = 22) {
    const p = part(6, name, spec);
    box(p, x0, x1, y0, y1, 0, 3.2, "black", 0.15);
    box(p, x0 - 0.2, x0 + 1.2, y0 - 0.4, y1 + 0.4, 3.2, 4.2, "latch", 0.2);
    box(p, x0 + 1.5, x0 + 2.1, y0 + 1.0, y1 - 1.0, 3.15, 3.25, "hole");
    const list = [];
    for (let i = 0; i < teeth; i++) {
      const y = y0 + 1.4 + (i * (y1 - y0 - 2.8)) / (teeth - 1);
      list.push([x0 + 2.2, x1 + 0.25, y - 0.12, y + 0.12, 0, 0.15]);
    }
    boxes(p, list, "gold");
  }
  ffc(46.6, 50.0, 5.5, 23.0, "MIPI connector 0", "22-pin 0.5 mm FFC · 4-lane camera or display");
  ffc(52.3, 55.5, 5.5, 23.0, "MIPI connector 1", "22-pin 0.5 mm FFC · 4-lane camera or display");
  ffc(0.6, 3.9, 22.5, 36.1, "PCIe connector", "16-pin FFC · PCIe 2.0 ×1 for NVMe HATs", 16);

  // ── Underside ──────────────────────────────────────────────────────────────────────────
  {
    const sd = part(7, "microSD card slot", "Push-push slot · SDR104 (104 MB/s)");
    box(sd, 1.0, 15.0, 22.0, 34.0, -T - 1.5, -T, "shell", 0.2);
    box(sd, -2.0, 11.0, 23.0, 33.0, -T - 1.2, -T - 0.4, "sd", 0.3);
  }
  {
    const under = part(7, "Underside passives", "Bulk capacitors and filtering on the bottom layer");
    const list = [];
    for (let x = 26; x <= 40; x += 2.0) list.push([x, x + 1.0, 22.5, 23.0, -T - 0.5, -T]);
    for (let x = 54; x <= 62; x += 2.0) list.push([x, x + 1.0, 35.0, 35.5, -T - 0.5, -T]);
    boxes(under, list, "cap");
  }

  return { root, groups, parts, materials: mats };
}
