// The parts in radar-led-demo.md: radar, breadboard, power module, jumpers, Jetson Nano, camera.
import * as THREE from "three";
import { model, at } from "../kit.js";

export function radar() {
  const k = model("HLK-LD2402 24 GHz radar", [
    { name: "Board and antennas", offset: [0, 0, 0], delay: 0 },
    { name: "Underside parts", offset: [0, -7, 0], delay: 0.06 },
    { name: "Header", offset: [0, -14, 0], delay: 0.1 },
  ]);
  const T = 1.0;
  const pcb = k.part(0, "PCB", "20 × 20 mm · RF laminate with the antennas etched on top");
  k.box(pcb, -10, 10, -10, 10, -T, 0, "pcbBlue", 0.6);
  const tx = k.part(0, "TX patch antenna", "24 GHz microstrip patches: radiate the chirp toward the room");
  const rx = k.part(0, "RX patch antennas", "Receive the reflection; the frequency shift and phase give distance and motion");
  const patch = (target, cx, cy) => k.box(target, cx - 1.6, cx + 1.6, cy - 1.9, cy + 1.9, 0, 0.04, "gold");
  for (const cy of [4.6, -0.6]) patch(tx, -5.2, cy);
  k.box(tx, -5.35, -5.05, -2.5, 6.5, 0, 0.035, "gold");
  for (const cx of [1.4, 6.2]) for (const cy of [4.6, -0.6]) patch(rx, cx, cy);
  k.box(rx, 1.25, 1.55, -2.5, 6.5, 0, 0.035, "gold");
  k.box(rx, 6.05, 6.35, -2.5, 6.5, 0, 0.035, "gold");
  k.label(pcb, 0, -5.8, 0, 14, 1.6, [["V   G   IO  TX  RX", 1]], { color: "#e8eef8" });
  k.label(pcb, 0, -3.6, 0, 10, 1.2, [["HLK-LD2402", 1]], { color: "#e8eef8" });
  const soc = k.part(1, "Radar SoC", "24 GHz FMCW transceiver with a built-in processor running the presence algorithm");
  k.box(soc, -3, 3, 0, 6, -T - 0.9, -T, "chip", 0.15);
  const ldo = k.part(1, "3.3 V regulator", "Low-dropout regulator for the RF supply");
  k.box(ldo, 4, 7, 2, 4, -T - 1.1, -T, "chip", 0.1);
  const xtal = k.part(1, "Crystal", "Reference clock for the chirp synthesiser");
  k.box(xtal, -7.5, -5, 1.5, 3.5, -T - 0.8, -T, "steel", 0.15);
  const caps = k.part(1, "Passives", "Decoupling and RF filtering");
  const list = [];
  for (let i = 0; i < 6; i++) list.push([-6 + i * 2.2, -5.2 + i * 2.2, 7.4, 7.9, -T - 0.5, -T]);
  for (let i = 0; i < 4; i++) list.push([4.2 + (i % 2) * 2, 5.2 + (i % 2) * 2, -1.6 - Math.floor(i / 2) * 1.6, -1.1 - Math.floor(i / 2) * 1.6, -T - 0.5, -T]);
  k.boxes(caps, list, "ceramic");
  const header = k.part(2, "5-pin header", "V · G · IO · TX · RX at 2.54 mm. IO goes high (~3.3 V) when someone is present; TX/RX are 3.3 V UART at 115200");
  k.box(header, -6.35, 6.35, -8.97, -6.43, -T - 2.5, -T, "black", 0.1);
  k.pins(header, 5, 1, 0, -7.7, -T - 2.5 - 6, 1.5, "gold");
  return k.done({
    spec: "24 GHz presence radar · 20 × 20 mm · supply 3.0–3.6 V on many listings (check yours) · IO output + UART",
    pins: ["V", "G", "IO", "TX", "RX"].map((name, i) => ({ x: -5.08 + i * 2.54, y: -7.7, name })),
    tip: -T - 8.5,
    insert: 5.5,
  });
}

export function breadboard({ rows = 30 } = {}) {
  const full = rows > 30;
  const k = model(full ? `Full-size breadboard (${rows} rows)` : "Half-size breadboard (400 points)", [
    { name: "Spring clips", offset: [0, 0, 0], delay: 0.06 },
    { name: "Plastic body", offset: [0, 16, 0], delay: 0 },
    { name: "Adhesive backing", offset: [0, -8, 0], delay: 0.1 },
  ]);
  const W = rows * 2.54 + 6.3, D = 54.5, H = 8.5;
  const x0 = -((rows - 1) * 2.54) / 2, rail = W / 2 - 5.25;
  const cols = Array.from({ length: rows }, (_, i) => x0 + i * 2.54);
  const rowsF = [0, 1, 2, 3, 4].map((i) => 3.81 + i * 2.54);
  const mainRows = [...rowsF.map((y) => -y).reverse(), ...rowsF];
  const railY = [-24.4, -21.86, 21.86, 24.4];
  const railX = cols.filter((_, i) => i % 6 !== 5 && i < rows - 1).map((x) => x + 2.54);
  const body = k.part(1, "ABS body", `${rows} columns × rows a–j, a 7.62 mm centre channel for DIP chips, and two power rails each side`);
  k.box(body, -W / 2, W / 2, -D / 2, D / 2, 0, H, "board", 0.8);
  k.box(body, -W / 2 + 1.5, W / 2 - 1.5, -1.6, 1.6, H - 1.8, H + 0.01, "foam");
  const holes = [];
  for (const x of cols) for (const y of mainRows) holes.push([x - 0.55, x + 0.55, y - 0.55, y + 0.55, H - 0.7, H + 0.012]);
  for (const x of railX) for (const y of railY) holes.push([x - 0.55, x + 0.55, y - 0.55, y + 0.55, H - 0.7, H + 0.012]);
  k.boxes(body, holes, "hole");
  k.boxes(body, [[-rail, rail, 20.2, 20.5, H, H + 0.015], [-rail, rail, -26.15, -25.85, H, H + 0.015]], "red");
  k.boxes(body, [[-rail, rail, 26.0, 26.3, H, H + 0.015], [-rail, rail, -20.5, -20.2, H, H + 0.015]], "blue");
  k.label(body, x0 - 2.37, 0, H, 2.2, 28, ["j", "i", "h", "g", "f", "", "e", "d", "c", "b", "a"], { color: "#8a8a8a" });
  // Row numbers: two characters per row, so the monospace text lines up with the holes.
  const numbers = full
    ? Array.from({ length: rows }, (_, i) => (i === 0 || (i + 1) % 5 === 0 ? String(i + 1) : "")).reduce((t, n, i) => t.padEnd(i * 2) + n, "")
    : "1         5         10        15        20        25        30";
  k.label(body, 0, 17.3, H, rows * 2.54, 1.6, [numbers], { color: "#8a8a8a" });
  const clips = k.part(0, "Spring clips", "Nickel-plated phosphor-bronze strips: each joins 5 holes in a column, the rails join along their length");
  const strips = [];
  for (const x of cols) for (const [y0, y1] of [[-14.6, -2.6], [2.6, 14.6]]) strips.push([x - 0.7, x + 0.7, y0, y1, 1.5, H - 0.9]);
  for (const y of railY) strips.push([-rail + 0.5, rail - 0.5, y - 0.7, y + 0.7, 1.5, H - 0.9]);
  k.boxes(clips, strips, "tin");
  const back = k.part(2, "Adhesive backing", "Foam tape that holds the clips in and sticks the board down");
  k.box(back, -W / 2 + 0.3, W / 2 - 0.3, -D / 2 + 0.3, D / 2 - 0.3, -0.6, 0, "foam", 0.6);
  // Every hole with its name: columns 1–30, rows a–e (front) and f–j (back) either side of the
  // channel; rails named by side and polarity (red line = +), numbered by the column they sit by.
  const holeList = [];
  "abcde".split("").forEach((r, i) => cols.forEach((x, c) => holeList.push({ x, y: -(3.81 + (4 - i) * 2.54), name: `${r}${c + 1}` })));
  "fghij".split("").forEach((r, i) => cols.forEach((x, c) => holeList.push({ x, y: 3.81 + i * 2.54, name: `${r}${c + 1}` })));
  const railName = { "-24.4": "front + rail", "-21.86": "front − rail", "21.86": "back + rail", "24.4": "back − rail" };
  for (const y of railY) railX.forEach((x) => holeList.push({ x, y, name: `${railName[y]} by row ${Math.round((x - x0) / 2.54) + 1}` }));
  return k.done({ spec: full ? `${W.toFixed(1)} × 54.5 × 8.5 mm · ${rows * 10 + railX.length * 4} tie points · 2.54 mm pitch` : "82.5 × 54.5 × 8.5 mm · 400 tie points · 2.54 mm pitch", holes: holeList, top: H });
}

export function powerModule() {
  const k = model("Breadboard power module (MB102)", [
    { name: "Board", offset: [0, 0, 0], delay: 0 },
    { name: "Inputs", offset: [0, -14, 4], delay: 0.06 },
    { name: "Regulators", offset: [0, 10, 0], delay: 0.1 },
    { name: "Rail pins and jumpers", offset: [0, -8, 0], delay: 0.14 },
  ]);
  const W = 53, D = 33.5;
  const RAILS = [-24.4, -21.86, 21.86, 24.4];
  const pcb = k.part(0, "PCB", "53 × 33.5 mm · plugs across the end of a breadboard so its pins land in both pairs of rails");
  k.box(pcb, -W / 2, W / 2, -D / 2, D / 2, -1.6, 0, "pcbRed", 1.2);
  k.label(pcb, 0, -2.5, 0, 14, 3, [["MB102", 1]], { color: "#f6f6f6" });
  k.label(pcb, -18.5, 15, 0, 9, 1.6, [["5V OFF 3V3", 1]], { color: "#f6f6f6" });
  k.label(pcb, 18.5, 15, 0, 9, 1.6, [["5V OFF 3V3", 1]], { color: "#f6f6f6" });
  const usb = k.part(1, "USB-A socket", "5 V in from a laptop or phone charger (the demo uses this)");
  k.box(usb, -14, 0, -18.5, -4.5, 0, 7, "shell", 0.3);
  k.box(usb, -12.6, -1.4, -18.6, -18.2, 1.2, 5.8, "hole", 0.1);
  k.box(usb, -11.6, -2.4, -18.7, -18.3, 3.6, 5.2, "black", 0.1);
  const jack = k.part(1, "DC barrel jack", "6.5–12 V in, 5.5 × 2.1 mm");
  k.box(jack, 2.5, 11.5, -18.5, -4.5, 0, 11, "black", 0.4);
  k.lathe(jack, [[3.2, 0], [3.2, 0.3], [2.6, 0.3], [2.6, 1], [0.95, 1], [0.95, 0]], [7, -18.55, 6.5], [0, -1, 0], "hole", 32);
  k.rod(jack, [7, -18.6, 6.5], [7, -14.5, 6.5], 0.95, "steel", { segments: 16 });
  const sw = k.part(1, "Power switch", "Latching push switch; the green LED shows power is on");
  k.box(sw, 14, 22, -15.5, -7.5, 0, 6.5, "black", 0.3);
  k.box(sw, 16, 20, -13.5, -9.5, 6.5, 9.5, "white", 0.4);
  k.box(sw, 23.2, 24.8, -15, -14, 0, 0.8, "ledGreen", 0.1).userData.powerLed = true;
  const reg = k.part(2, "AMS1117 regulators", "Two linear regulators: one 5 V, one 3.3 V (800 mA max, the 3.3 V one runs warm)");
  for (const x of [-10, 3.5]) {
    k.box(reg, x, x + 6.5, 0, 3.5, 0, 1.6, "chip", 0.1);
    k.box(reg, x + 0.75, x + 5.75, 3.5, 5.4, 0, 0.25, "tin");
    k.boxes(reg, [1.0, 3.25, 5.5].map((dx) => [x + dx - 0.35, x + dx + 0.35, -1.4, 0, 0, 0.25]), "tin");
  }
  const caps = k.part(2, "Filter capacitors", "Electrolytics on the input and both outputs");
  for (const [x, y] of [[-21, -8], [0, 11], [21, -1]]) {
    k.rod(caps, [x, y, 0], [x, y, 7], 2.5, "sleeveBlue", { segments: 32 });
    k.rod(caps, [x, y, 7], [x, y, 7.05], 2.3, "aluminium", { segments: 32 });
  }
  const jumpers = k.part(3, "Voltage jumpers", "One per rail pair: cap on 5V or 3V3 (OFF disconnects that side)");
  for (const x of [-18.5, 18.5]) {
    k.box(jumpers, x - 1.27, x + 1.27, 5.4, 13.0, 0, 2.5, "black", 0.1);
    k.pins(jumpers, 1, 3, x, 9.21, 2.5, 8.5, "gold");
    k.box(jumpers, x - 1.27, x + 1.27, 5.4, 10.5, 2.6, 8.6, "black", 0.3);
  }
  const pins = k.part(3, "Rail pins", "Eight pins underneath, two per rail: they drop into the + and − rails on both sides of the breadboard");
  for (const x of RAILS) k.pins(pins, 1, 2, x, 12.7, -1.6 - 8, -1.6, "gold");
  k.boxes(pins, RAILS.map((x) => [x - 1.2, x + 1.2, 10.2, 15.2, -4.1, -1.6]), "black");
  const names = ["left −", "left +", "right −", "right +"];
  return k.done({
    spec: "USB-A or 6.5–12 V in · 5 V and 3.3 V out to each rail pair · 700 mA max",
    pins: RAILS.flatMap((x, i) => [11.43, 13.97].map((y, j) => ({ x, y, name: `${names[i]} ${j + 1}` }))),
    tip: -1.6 - 8,
    insert: 5.5,
  });
}

export function jumperWires({ count = 4, span = 19 } = {}) {
  const reach = (span * 2.54) / 2;
  const k = model("Jumper wires (male–male)", [
    { name: "Wires and pins", offset: [0, 0, 0], delay: 0 },
    { name: "Housings", offset: [0, 9, 0], delay: 0.05 },
  ]);
  const colours = [["wireRed", "5 V"], ["wireBlack", "GND"], ["wireYellow", "IO (signal)"], ["wireGreen", "LED to GND"]].slice(0, count);
  const xOf = (i) => (i - (count - 1) / 2) * 6;
  const arc = Math.min(34, 10 + reach * 0.45);
  colours.forEach(([m, use], i) => {
    const x = xOf(i);
    const wire = k.part(0, `Wire · ${use}`, `22 AWG stranded, ${m.replace("wire", "").toLowerCase()} insulation`);
    const top = arc - i * 1.5;
    k.tube(wire, [[x, -reach, 13], [x, -reach + 2, Math.min(22, top - 2)], [x, -reach * 0.33, top], [x, reach * 0.33, top], [x, reach - 2, Math.min(22, top - 2)], [x, reach, 13]], 0.8, m, { segments: 80, radial: 14 });
    for (const y of [-reach, reach]) {
      k.box(wire, x - 0.35, x + 0.35, y - 0.35, y + 0.35, -7, 2, "gold");
      k.box(wire, x - 0.8, x + 0.8, y - 0.8, y + 0.8, 2, 9, "tin");
    }
  });
  const housings = k.part(1, "Dupont housings", "2.54 mm plastic shells over the crimped pins; slide off to reach the crimp");
  for (let i = 0; i < count; i++) for (const y of [-reach, reach]) {
    const x = xOf(i);
    k.box(housings, x - 1.27, x + 1.27, y - 1.27, y + 1.27, 1.5, 14, "black", 0.2);
  }
  return k.done({
    spec: "Dupont M–M · 2.54 mm · the demo uses 4–5: 5 V, GND, IO, LED to GND",
    pins: colours.flatMap((_, i) => [{ x: xOf(i), y: -reach, name: `wire ${i + 1} end A` }, { x: xOf(i), y: reach, name: `wire ${i + 1} end B` }]),
    tip: -7,
    insert: 5.5,
    spans: [2, 30],
  });
}

export function jetsonNano() {
  const k = model("Jetson Nano Developer Kit", [
    { name: "Carrier board", offset: [0, 0, 0], delay: 0 },
    { name: "Compute module", offset: [0, 14, 0], delay: 0.06 },
    { name: "Heatsink", offset: [0, 32, 0], delay: 0 },
    { name: "Front ports", offset: [0, 4, 18], delay: 0.12 },
    { name: "Headers and CSI", offset: [0, 16, -8], delay: 0.16 },
  ]);
  const W = 100, D = 80, x0 = -W / 2, y0 = -D / 2;
  const X = (x) => x0 + x, Y = (y) => y0 + y;
  const carrier = k.part(0, "Carrier board (P3449)", "100 × 80 mm · breaks the module's 260-pin edge out to the ports");
  k.plate(carrier, W, D, -1.6, 1.6, "pcbGreen", { r: 2, x0, y0, holes: [[X(4), Y(4), 1.5], [X(96), Y(4), 1.5], [X(4), Y(76), 1.5], [X(96), Y(76), 1.5]] });
  for (const [x, y] of [[4, 4], [96, 4], [4, 76], [96, 76]]) k.rod(carrier, [X(x), Y(y), -1.6], [X(x), Y(y), -9], 2.5, "aluminium", { segments: 6 });
  const sodimm = k.part(0, "SO-DIMM socket", "260-pin socket holding the compute module above the carrier");
  k.box(sodimm, X(15), X(85), Y(38), Y(44), 0, 5, "black", 0.3);
  const m2 = k.part(0, "M.2 Key E slot", "For a Wi-Fi card, under the module");
  k.box(m2, X(40), X(62), Y(22), Y(27), 0, 3, "black", 0.2);
  const module = k.part(1, "Jetson Nano module (P3448)", "69.6 × 45 mm · 4× Cortex-A57 @ 1.43 GHz, 128-core Maxwell GPU, 4 GB LPDDR4, 16 GB eMMC");
  k.box(module, X(15.2), X(84.8), Y(32), Y(77), 5, 6.2, "pcbGreen", 0.6);
  k.box(module, X(22), X(36), Y(48), Y(62), 6.2, 7.2, "chip", 0.3);
  k.box(module, X(64), X(76), Y(50), Y(62), 6.2, 7.2, "chip", 0.3);
  k.box(module, X(62), X(80), Y(36), Y(46), 6.2, 7.0, "chip", 0.3);
  const sink = k.part(2, "Heatsink", "Extruded aluminium, 60 × 40 mm; a 5 V fan can bolt on top");
  k.box(sink, X(20), X(80), Y(36), Y(76), 7.2, 10.2, "aluminium", 0.5);
  const fins = [];
  for (let i = 0; i < 13; i++) { const x = X(21) + i * 4.85; fins.push([x, x + 1.4, Y(36), Y(76), 10.2, 26.5]); }
  k.boxes(sink, fins, "aluminium");
  const fp = k.part(3, "Rear I/O", "Barrel jack, micro-USB, HDMI, DisplayPort, 4× USB 3.0, Gigabit Ethernet");
  // Barrel jack (5 V ⎓ 4 A), micro-USB (5 V ⎓ 2 A), HDMI, DP, two USB stacks, RJ45 along the front edge.
  k.box(fp, X(2), X(11), Y(-1), Y(13), 0, 11, "black", 0.4);
  k.lathe(fp, [[3.2, 0], [3.2, 0.3], [2.6, 0.3], [2.6, 1], [0.95, 1], [0.95, 0]], [X(6.5), Y(-1.05), 6.5], [0, -1, 0], "hole", 32);
  k.box(fp, X(13), X(21), Y(-0.8), Y(5), 0, 3, "shell", 0.3);
  k.box(fp, X(13.8), X(20.2), Y(-0.9), Y(-0.5), 0.6, 2.4, "hole", 0.2);
  k.box(fp, X(23), X(38), Y(-1), Y(11), 0, 6.5, "shell", 0.4);
  k.box(fp, X(24.2), X(36.8), Y(-1.1), Y(-0.6), 1.2, 5.5, "hole", 0.3);
  k.box(fp, X(40), X(53), Y(-1), Y(11), 0, 5.6, "shell", 0.4);
  k.box(fp, X(41.2), X(51.8), Y(-1.1), Y(-0.6), 1.0, 4.6, "hole", 0.3);
  for (const ux of [55, 69]) {
    k.box(fp, X(ux), X(ux + 13.1), Y(-2), Y(15.4), 0, 15.6, "shell", 0.5);
    for (const z0 of [1.4, 9.0]) {
      k.box(fp, X(ux + 0.8), X(ux + 12.3), Y(-2.1), Y(-1.6), z0, z0 + 5.3, "hole", 0.3);
      k.box(fp, X(ux + 2), X(ux + 11.1), Y(-2.15), Y(-1.7), z0 + 2.6, z0 + 4.4, "blue", 0.15);
    }
  }
  k.box(fp, X(83.6), X(99.6), Y(-2), Y(19), 0, 13.5, "shell", 0.5);
  k.box(fp, X(85.8), X(97.4), Y(-2.1), Y(-1.5), 3.0, 10.4, "hole", 0.2);
  k.box(fp, X(84.3), X(86.3), Y(-2.15), Y(-1.8), 11.1, 12.5, "ledGreen", 0.1);
  k.box(fp, X(96.9), X(98.9), Y(-2.15), Y(-1.8), 11.1, 12.5, "ledAmber", 0.1);
  const gpio = k.part(4, "40-pin header (J41)", "Raspberry Pi-compatible pinout · 3.3 V logic");
  k.box(gpio, X(21.6), X(72.4), Y(73.4), Y(78.5), 0, 2.5, "black", 0.15);
  k.pins(gpio, 20, 2, X(47), Y(75.95), -1.6 - 3, 8.5, "gold");
  const csi = k.part(4, "CSI camera connectors", "2× 15-pin MIPI CSI-2 · Raspberry Pi Camera v2 (IMX219) compatible");
  for (const y of [52, 62]) {
    k.box(csi, X(90), X(94.5), Y(y), Y(y + 22 - 4), 0, 3.4, "black", 0.15);
    k.box(csi, X(89.8), X(91.2), Y(y - 0.4), Y(y + 18.4), 3.4, 4.4, "latch", 0.2);
  }
  const btn = k.part(4, "Button header (J40)", "Power, reset and recovery-mode pins");
  k.box(btn, X(4), X(14), Y(60), Y(65), 0, 2.5, "black", 0.1);
  k.pins(btn, 4, 2, X(9), Y(62.5), 0, 8.5, "gold");
  return k.done({ spec: "100 × 80 × 29 mm · 5 V ⎓ 4 A barrel jack recommended (own supply, not shared with the radar). Port layout approximate." });
}

export function csiCamera() {
  const k = model("CSI camera (Raspberry Pi Camera v2)", [
    { name: "Board", offset: [0, 0, 0], delay: 0.06 },
    { name: "Lens and sensor", offset: [0, 10, 0], delay: 0 },
    { name: "Ribbon", offset: [0, 0, 14], delay: 0.1 },
  ]);
  const W = 25, D = 23.86, x0 = -W / 2, y0 = -D / 2;
  const holes = [[2, 2], [23, 2], [2, 14.5], [23, 14.5]].map(([x, y]) => [x0 + x, y0 + D - y, 1.1]);
  const pcb = k.part(0, "PCB", "25 × 23.86 mm · four Ø2.2 mm holes, 21 × 12.5 mm apart");
  k.plate(pcb, W, D, -1, 1, "pcbGreen", { r: 1, x0, y0, holes });
  for (const [x, y] of holes) k.ring(pcb, x, y, 0.005, 1.1, 1.9, "gold");
  k.label(pcb, 0, y0 + 4.2, 0, 14, 1.4, [["Raspberry Pi Camera V2.1", 1]], { color: "#f2f2ee" });
  const conn = k.part(0, "FFC connector", "15-pin, 1 mm pitch ribbon connector on the back edge");
  k.box(conn, -10.5, 10.5, y0, y0 + 5.5, -1 - 2.5, -1, "black", 0.2);
  const lensY = y0 + D - 9.4;
  const sensor = k.part(1, "IMX219 sensor", "Sony 8 MP, 1/4 in, 1.12 µm pixels · 3280 × 2464");
  k.box(sensor, -4.25, 4.25, lensY - 4.25, lensY + 4.25, 0, 2.2, "black", 0.3);
  k.box(sensor, -2.4, 2.4, lensY - 1.8, lensY + 1.8, 2.2, 2.25, "die");
  const lens = k.part(1, "Lens barrel", "Fixed-focus f/2.0, 3.04 mm · 62.2° × 48.8° field of view");
  k.lathe(lens, [[3.6, 0], [3.6, 1.6], [3.2, 1.8], [3.2, 3.6], [2.5, 3.9], [0, 3.95]], [0, lensY, 2.25], [0, 0, 1], "black", 40);
  k.rod(lens, [0, lensY, 6.15], [0, lensY, 6.25], 2.0, "lens", { segments: 32 });
  const flex = k.part(1, "Sensor flex", "Short gold flex from the sensor to the board connector");
  k.box(flex, -3, 3, y0 + 2, lensY - 4.25, 0.2, 0.35, "copper");
  const ribbon = k.part(2, "Ribbon cable", "15-way, 16 mm wide · contacts face the board's connector");
  k.box(ribbon, -8, 8, y0 - 30, y0 + 3, -2.6, -2.4, "white");
  k.box(ribbon, -8, 8, y0 - 30, y0 - 26, -2.65, -2.35, "blue");
  return k.done({ spec: "Sony IMX219 · 8 MP · MIPI CSI-2 · plugs into the Jetson's CSI port" });
}

// One jumper wire between two points: a and b are [x, y] or [x, y, z] in board coordinates
// (z = 0 is the board top; a device's header socket sits higher). Used by the breadboard's wire
// tool, where rails sit off the row grid, and for wires out to an Arduino's headers.
export function wire({ a = [0, -10], b = [0, 10], colour = "wireRed", label = "" } = {}) {
  const k = model("Jumper wire", [{ name: "Wire", offset: [0, 0, 0], delay: 0 }]);
  const p = k.part(0, `Jumper wire${label ? ` · ${label}` : ""}`, "Dupont M–M, 22 AWG");
  const za = a[2] ?? 0, zb = b[2] ?? 0;
  const dx = b[0] - a[0], dy = b[1] - a[1], len = Math.hypot(dx, dy) || 1;
  const top = Math.max(za, zb) + 15 + Math.min(18, len * 0.35);
  const along = (t, z) => [a[0] + dx * t, a[1] + dy * t, z];
  const lift = Math.min(0.12, 3 / len);
  const path = [along(0, za + 13), along(lift * 0.4, top - 4), along(0.3, top), along(0.7, top), along(1 - lift * 0.4, top - 4), along(1, zb + 13)];
  k.tube(p, path, 0.8, colour, { segments: 80, radial: 12 });
  for (const [x, y, z = 0] of [a, b]) {
    k.box(p, x - 0.32, x + 0.32, y - 0.32, y + 0.32, z - 6, z + 2, "gold");
    k.box(p, x - 1.27, x + 1.27, y - 1.27, y + 1.27, z + 0.3, z + 14, "black", 0.2);
  }
  return k.done({ spec: "Dupont M–M jumper", pins: [{ x: a[0], y: a[1], name: "end A" }, { x: b[0], y: b[1], name: "end B" }], tip: -6, insert: 6, path });
}

// Arduino Uno R3: powers the board from its 5 V pin and reads test points on A0–A2 and D2.
// Pin positions follow the Uno's header layout (x from the USB edge, y from the power-header edge).
export const UNO_PINS = {
  "IOREF": [29.21, 2.54], "RESET": [31.75, 2.54], "3.3V": [34.29, 2.54], "5V": [36.83, 2.54], "GND": [39.37, 2.54], "GND 2": [41.91, 2.54], "VIN": [44.45, 2.54],
  "A0": [49.53, 2.54], "A1": [52.07, 2.54], "A2": [54.61, 2.54], "A3": [57.15, 2.54], "A4": [59.69, 2.54], "A5": [62.23, 2.54],
  "D0": [64.77, 50.8], "D1": [62.23, 50.8], "D2": [59.69, 50.8], "D3": [57.15, 50.8], "D4": [54.61, 50.8], "D5": [52.07, 50.8], "D6": [49.53, 50.8], "D7": [46.99, 50.8],
  "D8": [42.93, 50.8], "D9": [40.39, 50.8], "D10": [37.85, 50.8], "D11": [35.31, 50.8], "D12": [32.77, 50.8], "D13": [30.23, 50.8], "GND 3": [27.69, 50.8],
};
export function arduinoUno() {
  const k = model("Arduino Uno R3", [
    { name: "Board", offset: [0, 0, 0], delay: 0 },
    { name: "Microcontroller", offset: [0, 16, 0], delay: 0.05 },
    { name: "Connectors", offset: [0, 8, 0], delay: 0.1 },
  ]);
  const W = 68.6, D = 53.3, x0 = -W / 2, y0 = -D / 2, T = 1.6, top = T + 8.5;
  const X = (x) => x0 + x, Y = (y) => y0 + y;
  const pcb = k.part(0, "PCB", "68.6 × 53.3 mm · ATmega328P at 16 MHz, 5 V logic");
  k.plate(pcb, W, D, 0, T, "pcbBlue", { r: 1.5, x0, y0, holes: [[X(14), Y(2.5), 1.6], [X(15.3), Y(50.7), 1.6], [X(66.1), Y(7.6), 1.6], [X(66.1), Y(35.5), 1.6]] });
  k.label(pcb, X(40), Y(30), T, 22, 5, [["ARDUINO", 1], ["UNO", 0.8]], { color: "#f2f2ee", weight: 800, family: "ui-sans-serif, system-ui, sans-serif" });
  const mcu = k.part(1, "ATmega328P", "8-bit AVR, 32 KB flash, 10-bit ADC on A0–A5 (4.9 mV per step at 5 V)");
  k.box(mcu, X(30), X(65), Y(14), Y(22), T + 3, T + 7, "chip", 0.4);
  k.box(mcu, X(29.5), X(65.5), Y(13.5), Y(22.5), T, T + 3, "black", 0.3);
  k.label(mcu, X(47.5), Y(18), T + 7, 30, 4, [["ATMEGA328P-PU", 1]], { color: "#9a9a9e" });
  const usb = k.part(2, "USB-B socket", "Power and serial from the laptop: this is what \"plug in the Arduino\" means");
  k.box(usb, X(-6.2), X(9.8), Y(32), Y(44), T, T + 10.9, "shell", 0.5);
  k.box(usb, X(-6.3), X(-5.8), Y(34), Y(42), T + 2.5, T + 9, "hole", 0.3);
  const jack = k.part(2, "DC barrel jack", "7–12 V in");
  k.box(jack, X(-1.8), X(12.2), Y(3.3), Y(12.3), T, T + 11, "black", 0.4);
  const headers = k.part(2, "Female headers", "2.54 mm sockets: jumper wires plug in from above");
  const block = (x1, x2, y) => k.box(headers, X(x1), X(x2), Y(y - 1.27), Y(y + 1.27), T, top, "black", 0.15);
  block(25.9, 46.2, 2.54); block(48.3, 63.5, 2.54); block(26.4, 44.2, 50.8); block(45.7, 66.0, 50.8);
  k.boxes(headers, Object.values(UNO_PINS).map(([x, y]) => [X(x) - 0.45, X(x) + 0.45, Y(y) - 0.45, Y(y) + 0.45, top - 0.4, top + 0.01]), "hole");
  const led = k.part(0, "ON LED", "Lit when the board has power");
  k.box(led, X(29), X(30.6), Y(40), Y(41), T, T + 0.6, "ledGreen", 0.1).userData.powerLed = true;
  const pins = Object.entries(UNO_PINS).map(([name, [x, y]]) => ({ x: X(x), y: Y(y), z: top, name }));
  return k.done({ spec: "Arduino Uno R3 · USB powered · 5 V and GND to the rails, A0–A2 and D2 read the test points", pins, device: true, height: top });
}
