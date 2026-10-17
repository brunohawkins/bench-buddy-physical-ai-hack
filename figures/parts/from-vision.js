// What vision sees on the real bench → a twin layout that board.showLayout() draws and twin.js simulates.
//
//   fromVision(state, { usb, presence, leads })
//     state     vision.state() / the UI's SSE "board" event: { board: [{ id, part, colour, holes }], led, ... }
//               holes are "d20" or a rail "+top20" / "-bottom12" (vision.py parse_hole)
//     usb       the rails are powered (the tutor's usb step passed, or the user said so)
//     presence  someone is in front of the radar
//     leads     optional colour → radar pin, from what the user told the tutor ({ red: "V", black: "G" })
//   → { layout: { board, devices, parts, inputs }, unplaced: [{ id, part, why }] }
//
// The real build is the radar presence LED (curated.py RADAR_LED): the radar sits beside the board and
// its coloured leads plug in, so a wire with only one end on the board is a radar lead. Which pin it is
// comes from `leads` by colour, else from where it went: + rail → V, − rail → G, a row → IO.
import { stripOf } from "./twin.js";

export const LIVE_BOARD = "breadboard-full";
export const RADAR = { id: "hlk-ld2402-radar", name: "Radar", at: [-20, -52], rot: 0, lift: 9.5 };
const ROWS = 63;
const MB102 = { id: "breadboard-power-mb102", title: "USB power (laptop)", rot: 3, pins: { "left − 1": "back − rail by row 2", "left − 2": "back − rail by row 3", "left + 1": "back + rail by row 2", "left + 2": "back + rail by row 3", "right − 1": "front − rail by row 2", "right − 2": "front − rail by row 3", "right + 1": "front + rail by row 2", "right + 2": "front + rail by row 3" } };
const WIRE_COLOURS = { red: "red", black: "black", yellow: "yellow", green: "green", blue: "blue", orange: "orange", white: "yellow", brown: "orange", purple: "blue", violet: "blue", grey: "black", gray: "black" };
const PINS = ["V", "G", "IO", "TX", "RX"];

// "d20" → "d20"; "+top20" → "front + rail by row 20". Top rails sit above column a, which is the
// twin's front side. Rails skip every sixth row (the gaps on a real board), so a row there snaps over.
export function twinHole(h) {
  const s = String(h ?? "").trim().toLowerCase();
  let m = /^([a-j])(\d+)$/.exec(s);
  if (m) return +m[2] >= 1 && +m[2] <= ROWS ? `${m[1]}${+m[2]}` : null;
  m = /^([+-])(top|bottom)(\d+)$/.exec(s) || /^(top|bottom)([+-])(\d+)$/.exec(s);
  if (!m) return null;
  const [sign, side] = "+-".includes(m[1]) ? [m[1], m[2]] : [m[2], m[1]];
  let row = Math.min(ROWS, Math.max(1, +m[3]));
  if ((row - 1) % 6 === 0) row += 1;
  return `${side === "top" ? "front" : "back"} ${sign === "+" ? "+" : "−"} rail by row ${row}`;
}

const railSign = (hole) => /rail/.test(hole) ? (hole.includes(" + ") ? "+" : "−") : null;

// A radar lead's pin: by colour if the user said which colour is which, else by where it went.
function leadPin(colour, hole, leads, used) {
  const byColour = leads?.[String(colour ?? "").toLowerCase()];
  if (byColour && PINS.includes(byColour) && !used.has(byColour)) return byColour;
  const sign = railSign(hole);
  const guess = sign === "+" ? "V" : sign === "−" ? "G" : "IO";
  if (!used.has(guess)) return guess;
  return PINS.find((p) => !used.has(p)) ?? null;
}

export function fromVision(state, { usb = false, presence = false, leads = null } = {}) {
  const parts = [MB102];
  const unplaced = [];
  const used = new Set();
  const list = Array.isArray(state?.board) ? state.board : [];
  const holesOf = (p) => (p.holes ?? []).map(twinHole).filter(Boolean);
  const title = (p, what) => `${p.colour ? `${p.colour[0].toUpperCase()}${p.colour.slice(1)} ` : ""}${what}`;
  const lead = (p, hole) => {
    const pin = leadPin(p.colour, hole, leads, used);
    if (!pin) return unplaced.push({ id: p.id, part: p.part, why: "more leads than the radar has pins" });
    used.add(pin);
    parts.push({ id: "jumper-wire", title: `Radar ${pin} lead`, colour: WIRE_COLOURS[String(p.colour ?? "").toLowerCase()] ?? (pin === "G" ? "black" : pin === "V" ? "red" : "yellow"), pins: { "end A": `Radar ${pin}`, "end B": hole } });
  };

  // Resistors first, so an LED can tell which leg faces the resistor.
  const resistorStrips = new Set();
  for (const p of list) {
    if (p.part !== "resistor") continue;
    const hs = holesOf(p);
    if (hs.length < 2) { unplaced.push({ id: p.id, part: p.part, why: "only one leg seen" }); continue; }
    parts.push({ id: "resistor-1k", title: "R1 1 kΩ", pins: { 1: hs[0], 2: hs[1] } });
    hs.forEach((h) => resistorStrips.add(stripOf(h)));
  }
  for (const p of list) {
    const hs = holesOf(p);
    if (p.part === "resistor") continue;
    if (p.part === "wire") {
      if (hs.length >= 2) parts.push({ id: "jumper-wire", title: title(p, "wire"), colour: WIRE_COLOURS[String(p.colour ?? "").toLowerCase()] ?? "orange", pins: { "end A": hs[0], "end B": hs[1] } });
      else if (hs.length === 1) lead(p, hs[0]);                     // other end off the board: a radar lead
      else unplaced.push({ id: p.id, part: p.part, why: "no holes" });
    } else if (p.part === "radar") {
      for (const h of hs) lead(p, h);                                // the radar's leads, in its own entry
    } else if (p.part === "led") {
      if (hs.length < 2) { unplaced.push({ id: p.id, part: p.part, why: "only one leg seen" }); continue; }
      // Long leg (anode) faces the resistor; if neither does, a leg in a − rail is the cathode.
      let [a, k] = hs;
      if (!resistorStrips.has(stripOf(a)) && (resistorStrips.has(stripOf(k)) || railSign(a) === "−")) [a, k] = [k, a];
      parts.push({ id: "led-5mm-red", title: "LED", pins: { "+ (anode)": a, "− (cathode)": k } });
    } else {
      unplaced.push({ id: p.id, part: p.part, why: "not simulated" });
    }
  }
  return { layout: { board: LIVE_BOARD, devices: [RADAR], parts, inputs: { usb, presence } }, unplaced };
}

// The same layout as plain twin.setLayout() input (devices as parts whose pins are named terminals).
export function twinParts({ devices = [], parts = [] }) {
  return { parts: [...devices.map((d) => ({ id: d.id, title: d.name, device: true, pins: Object.fromEntries(PINS.map((n) => [n, `${d.name} ${n}`])) })), ...parts] };
}

// Pull "red is V, black is G, yellow is IO" out of what the user said at the radar step.
export function leadsFrom(text) {
  const out = {};
  const re = /\b(red|black|yellow|green|blue|orange|white|brown|purple|grey|gray)\b[^.,;]*?\b(v|vcc|g|gnd|ground|io|tx|rx)\b/gi;
  for (const [, colour, pin] of String(text ?? "").matchAll(re)) {
    const p = pin.toUpperCase();
    out[colour.toLowerCase()] = p === "VCC" ? "V" : p === "GND" || p === "GROUND" ? "G" : p;
  }
  return out;
}
