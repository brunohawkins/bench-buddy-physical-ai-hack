// Landing hero: the breadboard in white line art, a channel on the right that parts scroll
// through, and a loop that lifts one part off the board into the channel while another comes out.
import { createBoard, PARTS, partMarkup, partPoint, VIEWBOX } from "./board.mjs";

const NS = "http://www.w3.org/2000/svg";
const [VW, VH] = VIEWBOX;
const SWAP = ["chip", "c1", "led"];               // one of these is always out in the channel
const CHUTE = [
  { pi: true, label: "Raspberry Pi 4" },
  { part: "chip", label: "NE555 timer" },
  { part: "c1", label: "Capacitor · 10 µF" },
  { part: "r1", label: "Resistor · 10 kΩ" },
  { part: "led", label: "LED" },
  { pi: true, label: "Raspberry Pi 4" },
  { part: "chip", label: "NE555 timer" },
  { part: "c1", label: "Capacitor · 10 µF" },
];
const PART_SCALE = 0.95;                           // channel px per board unit
const EASE = "cubic-bezier(.45,0,.2,1)";
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const reduced = matchMedia("(prefers-reduced-motion: reduce)").matches;
const t = (x, y, k) => `translate(${x}px, ${y}px) scale(${k})`;

export async function createHero({ stage, boardEl, chute, landing }) {
  const board = createBoard(boardEl, { interactive: false });
  let missing = SWAP[SWAP.length - 1];
  let placed = PARTS.map((p) => p.id).filter((id) => id !== missing);
  board.set({ placed });

  const fly = document.createElementNS(NS, "svg");
  fly.setAttribute("class", "iso-svg fly");
  fly.setAttribute("viewBox", `0 0 ${VW} ${VH}`);
  stage.append(fly);

  const track = chute.querySelector(".chute-track");
  await fillChute(track);
  scrollChute(chute, track);
  if (reduced) return;

  // Where parts enter the channel, in board units: the slot halfway down its left wall.
  const slot = () => {
    const box = fly.getBoundingClientRect(), c = chute.getBoundingClientRect();
    const s = VW / box.width;
    return { x: (c.left + 10 - box.left) * s, y: (c.top + c.height / 2 - box.top) * s, s, k: PART_SCALE * s };
  };
  const flyer = (id) => {
    const g = document.createElementNS(NS, "g");
    g.setAttribute("class", "flyer");
    g.innerHTML = partMarkup(id);
    const [ax, ay] = partPoint(id);
    g.style.transformOrigin = `${ax}px ${ay}px`;
    fly.append(g);
    return { g, ax, ay };
  };

  async function flyOut(id) {
    placed = placed.filter((p) => p !== id);
    board.set({ placed });
    const { g, ax, ay } = flyer(id);
    const { x, y, s, k } = slot(), dx = x - ax, dy = y - ay;
    await g.animate([
      { transform: t(0, 0, 1), opacity: 1, easing: EASE },
      { transform: t(0, -42, 1.06), opacity: 1, offset: 0.2, easing: "ease-in-out" },
      { transform: t(dx * 0.5, dy * 0.5 - 90, (1 + k) / 2), opacity: 1, offset: 0.55, easing: "ease-out" },
      { transform: t(dx, dy, k), opacity: 1, offset: 0.84, easing: "ease-in" },
      { transform: t(dx + 70 * s, dy, k), opacity: 0 },
    ], { duration: 3000, fill: "forwards" }).finished;
    g.remove();
  }

  async function flyIn(id) {
    const { g, ax, ay } = flyer(id);
    const { x, y, s, k } = slot(), dx = x - ax, dy = y - ay;
    await g.animate([
      { transform: t(dx + 70 * s, dy, k), opacity: 0, easing: "ease-out" },
      { transform: t(dx, dy, k), opacity: 1, offset: 0.16, easing: "ease-in-out" },
      { transform: t(dx * 0.5, dy * 0.5 - 30, (1 + k) / 2), opacity: 1, offset: 0.48, easing: "ease-out" },
      { transform: t(0, -42, 1.06), opacity: 1, offset: 0.8, easing: EASE },
      { transform: t(0, 0, 1), opacity: 1 },
    ], { duration: 3000, fill: "forwards" }).finished;
    placed = [...placed, id];
    board.set({ placed });
    g.remove();
  }

  for (;;) {
    await sleep(1800);
    while (landing.hidden || document.hidden || !chute.offsetParent) await sleep(400);
    const out = SWAP[(SWAP.indexOf(missing) + 1) % SWAP.length];
    await flyOut(out);
    await flyIn(missing);
    missing = out;
  }
}

async function fillChute(track) {
  const pi = await fetch("assets/raspberry-pi.svg").then((r) => (r.ok ? r.text() : "")).catch(() => "");
  for (const item of CHUTE) {
    if (item.pi && !pi) continue;
    const el = document.createElement("figure");
    el.className = "chute-item";
    el.innerHTML = `${item.pi ? pi : `<svg class="iso-svg" viewBox="0 0 ${VW} ${VH}"><g>${partMarkup(item.part)}</g></svg>`}<figcaption>${item.label}</figcaption>`;
    track.append(el);
    // Crop each drawing to what's actually drawn.
    const svg = el.querySelector("svg"), b = svg.getBBox(), pad = 4;
    svg.setAttribute("viewBox", `${b.x - pad} ${b.y - pad} ${b.width + pad * 2} ${b.height + pad * 2}`);
    svg.style.width = item.pi ? "50%" : `${(b.width + pad * 2) * PART_SCALE}px`;
  }
}

function scrollChute(chute, track) {
  let anim;
  const run = () => {
    const dist = track.offsetHeight - chute.clientHeight;
    anim?.cancel();
    if (dist <= 0) return;
    anim = track.animate([{ transform: "translateY(0)" }, { transform: `translateY(${-dist}px)` }],
      { duration: dist * 60, iterations: Infinity, direction: "alternate", easing: "ease-in-out" });
    if (reduced) anim.pause();
  };
  run();
  new ResizeObserver(run).observe(chute);
}
