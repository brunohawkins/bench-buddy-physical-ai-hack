// Isometric breadboard drawn with the anatomy kit (vendor/iso-kit.mjs).
// The board is data: edit PARTS / rows below to match the real layout.
import * as k from "../vendor/iso-kit.mjs";

export const PITCH = 6;
export const ROWS = 63;                      // full-size board, same as calibrate.py --rows 63
const rowX0 = (row) => (row - 1) * PITCH;
const BOARD = { x: rowX0(1) - 10, y: -58, w: rowX0(ROWS) - rowX0(1) + 20, d: 116, r: 3 };
const BOARD_H = 9;
const W = 1000, H = 600;
const COL_Y = {
  a: -33, b: -27, c: -21, d: -15, e: -9, f: 9, g: 15, h: 21, i: 27, j: 33,
  "+L": -45, "-L": -51, "+R": 45, "-R": 51,
};
const COLS = "abcdefghij";
const RAILS = ["+L", "-L", "+R", "-R"];
export const rowX = rowX0;
export const hole = ([col, row]) => [rowX(row), COL_Y[col]];
const railHasRow = (row) => (row - 1) % 6 !== 5;

// Part list for the 555 astable. `from` is always the end Vision checks.
export const PARTS = [
  { id: "psu", kind: "supply", from: ["+L", 2], to: ["-L", 2], label: "5 V supply", detail: "Bench supply leads on the left rails" },
  { id: "bridge", kind: "wire", color: "red", from: ["+L", 4], to: ["+R", 4], lift: 16, label: "Rail bridge", detail: "Left 5 V rail → right 5 V rail" },
  { id: "chip", kind: "dip8", row: 10, label: "555 timer", detail: "Straddles the channel · pin 1 in row 10" },
  { id: "pwr", kind: "wire", color: "red", from: ["g", 10], to: ["+R", 8], label: "Power jumper", detail: "Pin 8 → 5 V rail" },
  { id: "gnd", kind: "wire", color: "black", from: ["d", 10], to: ["-L", 8], label: "Ground jumper", detail: "Pin 1 → GND rail" },
  { id: "r1", kind: "resistor", from: ["j", 10], to: ["j", 11], bands: ["brown", "black", "orange"], label: "R1 · 10 kΩ", detail: "Pin 8 → pin 7" },
  { id: "r2", kind: "resistor", from: ["i", 11], to: ["i", 12], bands: ["blue", "grey", "orange"], label: "R2 · 68 kΩ", detail: "Pin 7 → pin 6" },
  { id: "tie", kind: "wire", color: "yellow", from: ["g", 12], to: ["d", 11], lift: 15, label: "Trigger tie", detail: "Pin 6 → pin 2" },
  { id: "c1", kind: "cap", from: ["b", 11], to: ["-L", 10], label: "C1 · 10 µF", detail: "Pin 2 → GND" },
  { id: "r3", kind: "resistor", from: ["b", 12], to: ["b", 16], bands: ["orange", "orange", "brown"], label: "R3 · 330 Ω", detail: "Pin 3 → LED" },
  { id: "led", kind: "led", from: ["a", 16], to: ["-L", 17], label: "LED", detail: "R3 → GND" },
  { id: "rpd", kind: "resistor", from: ["-L", 13], to: ["a", 13], bands: ["brown", "black", "orange"], label: "Pull-down · 10 kΩ", detail: "Pin 4 → GND" },
  { id: "reset", kind: "wire", color: "red", from: ["c", 13], to: ["+L", 15], lift: 19, label: "Reset jumper", detail: "Pin 4 → 5 V rail" },
];
export const partById = (id) => PARTS.find((part) => part.id === id);

// Frame rows 1–30 (where the circuit lives); the rest of the board runs off to the right.
const VIEW = { x: BOARD.x - 6, y: BOARD.y, w: rowX0(30) - BOARD.x, d: BOARD.d, r: 0 };
const P = k.fitProjection(
  [...k.boxCorners(VIEW, -BOARD_H, 22)],
  W, H, { pad: 40, azimuth: 60, elevation: 38 },
);

const S = (paths, o) => k.solidSvg(paths, o);
const L = (d, o) => k.lineSvg(d, o);
const at = (p) => k.iso(p, P);
const bez = (p0, p1, p2, p3, n = 28) =>
  Array.from({ length: n + 1 }, (_, i) => {
    const t = i / n, u = 1 - t;
    return [0, 1, 2].map((j) => u * u * u * p0[j] + 3 * u * u * t * p1[j] + 3 * u * t * t * p2[j] + t * t * t * p3[j]);
  });
const path3 = (pts) => k.pathOf(pts.map(at));
const lead = (pts) => `<path class="lead" d="${path3(pts)}"/>`;
const near = (a, b) => k.depthOf([...a, 0], P) > k.depthOf([...b, 0], P);

function boardSvg() {
  const out = [`<path class="iso-halo" d="${k.haloOf(BOARD, -BOARD_H, BOARD_H, P)}"/>`];
  out.push(`<g class="m-board">${S(k.slabOf(BOARD, -BOARD_H, BOARD_H, P, 4, 0.8), { tone: "hi" })}`);
  // centre channel
  const x0 = BOARD.x + 3, x1 = BOARD.x + BOARD.w - 3;
  out.push(`<path class="channel" d="${k.planOutline({ x: x0, y: -3.2, w: x1 - x0, d: 6.4, r: 1 }, 0, P, 3)}"/>`);
  out.push(L(k.lineOnTop([x0, 0], [x1, 0], 0, P), { tone: "faint" }));
  for (const y of [-39.5, 39.5]) out.push(L(k.lineOnTop([x0, y], [x1, y], 0, P), { tone: "faint" }));
  // rail stripes
  for (const [y, c] of [[-41.6, "red"], [-54.6, "blue"], [41.6, "red"], [54.6, "blue"]])
    out.push(`<path class="stripe s-${c}" d="${k.lineOnTop([x0 + 3, y], [x1 - 3, y], 0, P)}"/>`);
  // holes
  const sq = (x, y, s = 1.15) => k.onTop([[x - s, y - s], [x + s, y - s], [x + s, y + s], [x - s, y + s]], 0, P, true);
  let d = "";
  for (let row = 1; row <= ROWS; row++) {
    for (const c of COLS) d += sq(...hole([c, row]));
    if (railHasRow(row)) for (const c of RAILS) d += sq(...hole([c, row]));
  }
  out.push(`<path class="holes" d="${d}"/>`);
  // row numbers and column letters
  for (const row of [1, ...Array.from({ length: Math.floor(ROWS / 5) }, (_, i) => (i + 1) * 5)]) {
    out.push(k.faceTextSvg(k.topMatrix([rowX(row), -36.4], 0, P), String(row), { size: 3, tone: "mid", anchor: "middle" }));
    out.push(k.faceTextSvg(k.topMatrix([rowX(row), 39], 0, P), String(row), { size: 3, tone: "mid", anchor: "middle" }));
  }
  for (const x of [rowX(0) - 0.5, rowX(ROWS + 1) + 0.5]) {
    for (const c of COLS) out.push(k.faceTextSvg(k.topMatrix([x, COL_Y[c] + 1.1], 0, P), c, { size: 3, tone: "mid", anchor: "middle" }));
    for (const [c, sign] of [["+L", "+"], ["-L", "−"], ["+R", "+"], ["-R", "−"]])
      out.push(k.faceTextSvg(k.topMatrix([x, COL_Y[c] + 1.2], 0, P), sign, { size: 3.6, tone: "mid", anchor: "middle" }));
  }
  out.push("</g>");
  return out.join("");
}

function supplySvg(part) {
  // Two flying leads from the bench supply, entering from off the left edge.
  return [[part.from, "red"], [part.to, "black"]].map(([spot, color]) => {
    const [x, y] = hole(spot);
    const d = path3(bez([x, y, 2.6], [x, y, 12], [x - 40, y - 4, 10], [x - 150, y - 30, -9]));
    return `<g class="wire w-${color}"><path class="pin" d="${k.rise([x, y], 0, 2.8, P)}"/><path class="w-case" d="${d}"/><path class="w-core" d="${d}"/><path class="w-shine" d="${d}"/></g>`;
  }).join("");
}

function dipSvg(part) {
  const x0 = rowX(part.row) - PITCH * 0.5 + 0.7;
  const x1 = rowX(part.row + 3) + PITCH * 0.5 - 0.7;
  const legs = (side) => {
    const out = [];
    for (let i = 0; i < 4; i++) {
      const x = rowX(part.row + i);
      const plan = side < 0 ? { x: x - 0.8, y: -9.7, w: 1.6, d: 3.4, r: 0.2 } : { x: x - 0.8, y: 6.3, w: 1.6, d: 3.4, r: 0.2 };
      out.push(S(k.slabOf(plan, 2.4, 1, P, 2), { tone: "hi", crease: "none" }));
      const foot = side < 0 ? { x: x - 0.8, y: -9.7, w: 1.6, d: 1, r: 0.2 } : { x: x - 0.8, y: 8.7, w: 1.6, d: 1, r: 0.2 };
      out.push(S(k.slabOf(foot, 0, 3.4, P, 2), { tone: "hi", crease: "none" }));
    }
    return `<g class="m-metal">${out.join("")}</g>`;
  };
  const body = { x: x0, y: -6.5, w: x1 - x0, d: 13, r: 0.8 };
  const notch = Array.from({ length: 13 }, (_, i) => {
    const a = -Math.PI / 2 + (Math.PI * i) / 12;
    return [x0 + Math.cos(a) * 2, Math.sin(a) * 2];
  });
  return [
    legs(-1),
    `<g class="m-chip">${S(k.slabOf(body, 1.6, 4.8, P, 3, 0.5), { tone: "hi" })}`,
    L(k.onTop(notch, 6.4, P), { tone: "lo" }),
    L(k.ring(x0 + 2.8, -3.8, 0.9, 6.4, P, 16), { tone: "lo" }),
    k.faceTextSvg(k.topMatrix([(x0 + x1) / 2 + 1, 1.3], 6.4, P), "NE555", { size: 3.4, tone: "lo", anchor: "middle" }),
    `</g>`,
    legs(1),
  ].join("");
}

const BAND_Z = [-2.2, -4, -5.8];
function resistorSvg(part) {
  const [ax, ay] = hole(part.from), [bx, by] = hole(part.to);
  const top = 13, r = 2.2;
  const body = [
    lead([[ax, ay, 0], [ax, ay, 2]]),
    `<g class="m-res">${S(k.cylinder(ax, ay, r, 2, top - 2, P, 24, 0.3), { tone: "hi" })}</g>`,
    ...part.bands.map((c, i) => `<path class="band b-${c}" d="${k.sideArc(ax, ay, r, top + BAND_Z[i], P, 16)}"/>`),
    `<path class="band b-gold" d="${k.sideArc(ax, ay, r, 4.2, P, 16)}"/>`,
  ].join("");
  const h = top + 4 + Math.hypot(bx - ax, by - ay) * 0.12;
  const wire = lead([...bez([ax, ay, top], [ax, ay, h + 2], [bx, by, h + 2], [bx, by, h - 3]), [bx, by, 0]]);
  return near([bx, by], [ax, ay]) ? body + wire : wire + body;
}

function capSvg(part) {
  const [ax, ay] = hole(part.from), [bx, by] = hole(part.to);
  const cx = (ax + bx) / 2, cy = (ay + by) / 2, r = 3.8, z0 = 3.5, z1 = 17;
  const legs = lead([[ax, ay, 0], [ax, ay, 1.2], [cx - 1.2 * Math.sign(bx - ax || 1), cy - 1.4, z0]]) +
    lead([[bx, by, 0], [bx, by, 1.2], [cx + 1.2, cy + 1.4, z0]]);
  const stripeA = (Math.PI * 2) / 3;
  const sx = cx + Math.cos(stripeA) * r, sy = cy + Math.sin(stripeA) * r;
  return [
    legs,
    `<g class="m-cap">${S(k.cylinder(cx, cy, r, z0, z1 - z0, P, 32, 0.4), { tone: "hi" })}`,
    `<path class="cap-stripe" d="${k.segment([sx, sy, z0 + 1.5], [sx, sy, z1 - 1.5], P)}"/>`,
    L(k.ring(cx, cy, r - 0.9, z1, P, 32), { tone: "lo" }),
    L(k.lineOnTop([cx - 2, cy], [cx + 2, cy], z1, P) + k.lineOnTop([cx, cy - 2], [cx, cy + 2], z1, P), { tone: "lo" }),
    `</g>`,
  ].join("");
}

function ledSvg(part, lit) {
  const [ax, ay] = hole(part.from), [bx, by] = hole(part.to);
  const cx = (ax + bx) / 2, cy = (ay + by) / 2;
  const glow = at([cx, cy, 11]);
  return [
    lead([[ax, ay, 0], [ax, ay, 1.5], [cx - 1, cy, 5]]) + lead([[bx, by, 0], [bx, by, 1.5], [cx + 1, cy, 5]]),
    `<g class="m-led">`,
    S(k.cylinder(cx, cy, 3, 5, 1.2, P, 28), { tone: "hi" }),
    S(k.cylinder(cx, cy, 2.6, 6.2, 4, P, 28), { tone: "hi", crease: "none" }),
    S(k.cylinder(cx, cy, 2.25, 10.2, 1, P, 24), { tone: "hi", crease: "none" }),
    S(k.cylinder(cx, cy, 1.6, 11.2, 0.7, P, 20), { tone: "hi", crease: "none" }),
    `</g>`,
    `<circle class="led-glow" cx="${glow[0]}" cy="${glow[1]}" r="46" fill="url(#ledGlow)"${lit ? "" : ' style="display:none"'}/>`,
  ].join("");
}

function wirePts(part) {
  const [ax, ay] = hole(part.from), [bx, by] = hole(part.to);
  const lift = part.lift ?? Math.max(9, 5 + Math.hypot(bx - ax, by - ay) * 0.3);
  return { ax, ay, bx, by, pts: bez([ax, ay, 2.6], [ax, ay, lift], [bx, by, lift], [bx, by, 2.6]) };
}
function wireSvg(part) {
  const { ax, ay, bx, by, pts } = wirePts(part);
  const d = path3(pts);
  const pin = (x, y) => `<path class="pin" d="${k.rise([x, y], 0, 2.8, P)}"/>`;
  return `<g class="wire w-${part.color}">${pin(ax, ay)}${pin(bx, by)}<path class="w-case" d="${d}"/><path class="w-core" d="${d}"/><path class="w-shine" d="${d}"/></g>`;
}

function anchorOf(part) {
  switch (part.kind) {
    case "dip8": return [rowX(part.row + 1.5), 0, 7];
    case "wire": return wirePts(part).pts[14];
    case "resistor": { const [x, y] = hole(part.from); return [x, y, 17]; }
    case "supply": { const [x, y] = hole(part.from); return [x - 12, y + 3, 11]; }
    default: { const [ax, ay] = hole(part.from), [bx, by] = hole(part.to); return [(ax + bx) / 2, (ay + by) / 2, 18]; }
  }
}
function sortKey(part) {
  const [x, y] = part.kind === "dip8" ? [rowX(part.row + 1.5), 0] : part.kind === "supply" ? [rowX(-20), 0] : anchorOf(part);
  return k.depthOf([x, y, 0], P) + (part.kind === "wire" ? 6 : 0);
}

function partSvg(part, lit) {
  switch (part.kind) {
    case "supply": return supplySvg(part);
    case "dip8": return dipSvg(part);
    case "resistor": return resistorSvg(part);
    case "cap": return capSvg(part);
    case "led": return ledSvg(part, lit);
    case "wire": return wireSvg(part);
  }
  return "";
}

export const VIEWBOX = [W, H];
export const partMarkup = (id) => partSvg(partById(id), false);
export const partPoint = (id) => at(anchorOf(partById(id)));

const ringAt = (spot, cls) => {
  const [x, y] = hole(spot);
  return `<g class="${cls}"><path d="${k.ring(x, y, 3.2, 0.1, P, 28)}"/><path d="${k.ring(x, y, 5.4, 0.1, P, 32)}" class="outer"/></g>`;
};

export function createBoard(el, { interactive = true } = {}) {
  el.classList.add("board");
  el.innerHTML = `<svg class="iso-svg" viewBox="0 0 ${W} ${H}" role="img" aria-label="Isometric view of the breadboard and the parts placed on it"></svg><div class="tags"></div>`;
  const svg = el.querySelector("svg");
  const tagLayer = el.querySelector(".tags");
  let st = { placed: PARTS.map((p) => p.id), ghost: null, targets: [], wrong: [], overrides: {}, focus: null, led: false, hz: 1, tags: [] };
  let shown = new Set();

  const geometry = (id) => ({ ...partById(id), ...(st.overrides[id] || {}) });

  function render() {
    const items = PARTS.filter((p) => st.placed.includes(p.id) || st.ghost === p.id).map((p) => geometry(p.id));
    items.sort((a, b) => sortKey(a) - sortKey(b));
    const fresh = [];
    const parts = items.map((p) => {
      const state = st.placed.includes(p.id) ? "placed" : "ghost";
      if (state === "placed" && !shown.has(p.id)) fresh.push(p.id);
      const delay = fresh.indexOf(p.id);
      const cls = ["part", state, st.focus === p.id ? "focus" : "", delay >= 0 && shown.size ? "drop" : "", delay >= 0 && !shown.size ? "intro" : ""].join(" ");
      return `<g class="${cls}" data-part="${p.id}" style="--d:${Math.max(0, delay) * 70}ms">${partSvg(p, st.led)}</g>`;
    });
    shown = new Set(st.placed);
    svg.innerHTML = [
      `<defs><radialGradient id="ledGlow"><stop offset="0" stop-color="#ff5a3c" stop-opacity=".85"/><stop offset=".35" stop-color="#ff3b2a" stop-opacity=".35"/><stop offset="1" stop-color="#ff3b2a" stop-opacity="0"/></radialGradient></defs>`,
      boardSvg(),
      st.targets.map((t) => ringAt(t, "target")).join(""),
      st.wrong.map((t) => ringAt(t, "wrong")).join(""),
      `<g class="parts${st.focus ? " has-focus" : ""}">${parts.join("")}</g>`,
    ].join("");
    svg.style.setProperty("--blink", `${(1 / (st.hz || 1)).toFixed(3)}s`);
    el.classList.toggle("lit", !!st.led);
    placeTags();
  }

  function toClient(point3) {
    const [sx, sy] = at(point3);
    const box = svg.getBoundingClientRect(), host = el.getBoundingClientRect();
    const s = box.width / W;
    return [box.left - host.left + sx * s, box.top - host.top + sy * s];
  }

  function placeTags() {
    const tags = [...st.tags];
    if (st.focus) {
      const p = partById(st.focus);
      tags.push({ part: st.focus, title: p.label, text: p.detail, tone: "focus" });
    }
    tagLayer.innerHTML = tags.map((t) => {
      const point = t.part ? anchorOf(geometry(t.part)) : [...hole(t.at), 3];
      const [x, y] = toClient(point);
      return `<div class="tag tone-${t.tone || "info"}" style="left:${x}px;top:${y}px">${t.title ? `<b>${t.title}</b>` : ""}<span>${t.text}</span></div>`;
    }).join("");
  }

  new ResizeObserver(placeTags).observe(el);
  if (interactive) {
    svg.addEventListener("pointerover", (e) => {
      const g = e.target.closest("[data-part]");
      el.dispatchEvent(new CustomEvent("part-hover", { detail: g ? g.dataset.part : null }));
    });
    svg.addEventListener("pointerleave", () => el.dispatchEvent(new CustomEvent("part-hover", { detail: null })));
  }

  return {
    set(patch) {
      st = { ...st, ...patch };
      if (Object.keys(patch).every((key) => key === "focus" || key === "tags")) {
        // cheap path for hover: no re-render, so animations keep running
        svg.querySelector(".parts")?.classList.toggle("has-focus", !!st.focus);
        svg.querySelectorAll("[data-part]").forEach((g) => g.classList.toggle("focus", g.dataset.part === st.focus));
        placeTags();
      } else render();
    },
    get: () => st,
    reveal(ids) { shown = new Set(); st = { ...st, placed: ids }; render(); },
  };
}
