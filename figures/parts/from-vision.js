// What vision sees on the real bench → a twin layout that board.showLayout() draws and twin.js simulates.
//
//   fromVision(state, { usb, presence, leads, radar, ohms })
//     state     vision.state() / the UI's SSE "board" event: { board: [{ id, part, colour, holes }], led, ... }
//               holes are "d20" or a rail "+top20" / "-bottom12" (vision.py parse_hole)
//     usb       the rails are powered (the tutor's usb step passed, or the user said so)
//     presence  someone is in front of the radar
//     leads     optional colour → radar pin, from what the user told the tutor ({ red: "V", black: "G" })
//     radar     the build uses a radar module (said in the conversation); vision naming one also counts
//     ohms      the resistor's value from the parts the user listed (default 1 kΩ)
//   → { layout: { board, devices, parts, inputs }, unplaced: [{ id, part, why }] }
//
// Radar pin identities come from the user's colour map. An unidentified wire stays loose: inferring V/G
// from the destination rail would hide a lead plugged into the wrong rail.
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

const colourKey = (colour) => String(colour ?? "").toLowerCase().replace(/^gray$/, "grey");

function leadPin(colour, leads, used) {
  const byColour = leads?.[colourKey(colour)];
  if (byColour && PINS.includes(byColour) && !used.has(byColour)) return byColour;
  return null;
}

const RESISTORS = [[220, "resistor-220r"], [330, "resistor-330r"], [1000, "resistor-1k"], [10000, "resistor-10k"], [68000, "resistor-68k"]];
const resistorFor = (ohms) => RESISTORS.reduce((a, b) => (Math.abs(Math.log(b[0] / ohms)) < Math.abs(Math.log(a[0] / ohms)) ? b : a));
const ohmsText = (o) => (o >= 1000 ? `${+(o / 1000).toPrecision(3)} kΩ` : `${o} Ω`);

export function fromVision(state, { usb = false, presence = false, leads = null, radar = false, ohms = 1000 } = {}) {
  const parts = usb ? [MB102] : [];                // an empty, unpowered board must start empty
  const unplaced = [];
  const used = new Set();
  const list = Array.isArray(state?.board) ? state.board : [];
  const hasRadar = radar || list.some((p) => p.part === "radar");
  const [value, resistorId] = resistorFor(ohms || 1000);
  const holesOf = (p) => (p.holes ?? []).map(twinHole).filter(Boolean);
  const title = (p, what) => `${p.colour ? `${p.colour[0].toUpperCase()}${p.colour.slice(1)} ` : ""}${what}`;
  const lead = (p, hole) => {
    const pin = leadPin(p.colour, leads, used);
    if (!pin) {
      unplaced.push({ id: p.id, part: p.part, why: "radar pin identity is unknown or duplicated" });
      parts.push({ id: "jumper-wire", title: title(p, "unidentified lead"), colour: WIRE_COLOURS[colourKey(p.colour)] ?? "orange", pins: { "end B": hole } });
      return;
    }
    used.add(pin);
    parts.push({ id: "jumper-wire", title: `Radar ${pin} lead`, colour: WIRE_COLOURS[String(p.colour ?? "").toLowerCase()] ?? (pin === "G" ? "black" : pin === "V" ? "red" : "yellow"), pins: { "end A": `Radar ${pin}`, "end B": hole } });
  };

  // Resistors first, so an LED can tell which leg faces the resistor.
  const resistorStrips = new Set();
  for (const p of list) {
    if (p.part !== "resistor") continue;
    const hs = holesOf(p);
    if (hs.length < 2) { unplaced.push({ id: p.id, part: p.part, why: "only one leg seen" }); continue; }
    parts.push({ id: resistorId, title: `${p.id && p.id !== "r1" ? p.id.toUpperCase() : "R1"} ${ohmsText(value)}`, pins: { 1: hs[0], 2: hs[1] } });
    hs.forEach((h) => resistorStrips.add(stripOf(h)));
  }
  for (const p of list) {
    const hs = holesOf(p);
    if (p.part === "resistor") continue;
    if (p.part === "wire") {
      if (hs.length >= 2) parts.push({ id: "jumper-wire", title: title(p, "wire"), colour: WIRE_COLOURS[String(p.colour ?? "").toLowerCase()] ?? "orange", pins: { "end A": hs[0], "end B": hs[1] } });
      else if (hs.length === 1 && hasRadar) lead(p, hs[0]);         // other end off the board: a radar lead
      else if (hs.length === 1) parts.push({ id: "jumper-wire", title: title(p, "wire (one end in)"), colour: WIRE_COLOURS[String(p.colour ?? "").toLowerCase()] ?? "orange", pins: { "end B": hs[0] } });
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
  return { layout: { board: LIVE_BOARD, devices: hasRadar ? [RADAR] : [], parts, inputs: { usb, presence } }, unplaced };
}

// The same layout as plain twin.setLayout() input (devices as parts whose pins are named terminals).
export function twinParts({ devices = [], parts = [] }) {
  return { parts: [...devices.map((d) => ({ id: d.id, title: d.name, device: true, pins: Object.fromEntries(PINS.map((n) => [n, `${d.name} ${n}`])) })), ...parts] };
}

// Targets for a spoken step: "Plug the IO lead into row 30 … row 35" → rows [30, 35]; "the plus rail" → rails ["+"].
export function targetsFrom(text) {
  const t = String(text ?? "");
  const rows = new Set();
  for (const m of t.matchAll(/\brows?\s+(\d{1,2})(?:\s*(?:and|to|through|-|–)\s*(\d{1,2}))?/gi)) {
    rows.add(+m[1]);
    if (m[2]) rows.add(+m[2]);
  }
  const rails = [];
  if (/\b(plus|positive|\+|5 ?v(?:olts?)?|red)\s+rail/i.test(t)) rails.push("+");
  if (/\b(minus|negative|-|−|ground|gnd|blue)\s+rail/i.test(t)) rails.push("−");
  return { rows: [...rows].filter((r) => r >= 1 && r <= ROWS), rails };
}

// Pull "red is V, black is G, yellow is IO" out of what the user said at the radar step.
export function leadsFrom(text) {
  const out = {};
  const colour = "(red|black|yellow|green|blue|orange|white|brown|purple|grey|gray)";
  const pin = "(vcc|gnd|ground|io|tx|rx|v|g)";
  const link = "\\s*(?:(?:lead is|wire is|goes to|is|lead|wire|:|=|->)\\s*)?";
  const re = new RegExp(`\\b(?:${colour}\\b${link}${pin}\\b|${pin}\\b${link}${colour}\\b)`, "gi");
  for (const [, c1, p1, p2, c2] of String(text ?? "").matchAll(re)) {
    const colour = c1 ?? c2, pin = p1 ?? p2;
    const p = pin.toUpperCase();
    out[colourKey(colour)] = p === "VCC" ? "V" : p === "GND" || p === "GROUND" ? "G" : p;
  }
  return out;
}
