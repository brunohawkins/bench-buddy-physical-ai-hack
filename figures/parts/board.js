// Breadboard mode: push parts into a half-size breadboard. A part's legs snap to real holes,
// the readout names the holes ("1 → a5, 2 → a9"), R turns the part, [ and ] stretch its leads
// over more or fewer holes, and jumper wires run between any two holes with two clicks.
// Everything placed is simulated live (twin.js): LEDs glow with their current, dots run along
// wires that carry current, a USB cable powers the MB102 from a laptop, and with no part picked
// (Esc) pointing at a hole shows its voltage and lights up every hole on the same net.
import { wire } from "./components/demo.js";
import { at } from "./kit.js";
import { createTwin } from "./twin.js";
import { fmtV, fmtI } from "./electrical.js";
import { PROJECTS, layoutOf, shiftRows } from "./projects.js";

const WIRE_COLOURS = [["wireRed", "red"], ["wireBlack", "black"], ["wireYellow", "yellow"], ["wireGreen", "green"], ["wireBlue", "blue"], ["wireOrange", "orange"]];
const TABLE = -0.6;            // the bench surface, in the breadboard model's frame (its foam backing sits on it)

// boardId picks the breadboard model ("breadboard-half", or "breadboard-full" for the real 63-row board);
// panelHost is where the simulation panel goes (default: after the gallery's .bar).
export function createBoard({ THREE, scene, camera, controls, canvas, CATALOG, decorate, frame, readout, legend, hold, boardId = "breadboard-half", panelHost = null }) {
  const group = new THREE.Group();
  group.name = "Breadboard layout";
  let bb = null;            // the breadboard model: { root, holes, top }
  let entry = null;         // the catalogue entry being placed
  let ghost = null;         // { root, pins, tip, insert, spans }
  let rot = 0, span = null, colour = 0, wireStart = null, lastHit = null;
  const placed = [];        // { id, title, rot, span, root, pins: [{ name, hole }] }
  const occupied = new Map(); // hole name → placed index
  let twin = null, panel = null, panelClock = 0, inspect = null, project = null;
  const terminals = new Map();   // device pin name ("Arduino A0") → { x, y, z } in board coordinates
  const glowColour = new THREE.Color(0xff2a1a);
  const ray = new THREE.Raycaster();
  const ndc = new THREE.Vector2();
  const plane = new THREE.Plane(new THREE.Vector3(0, 1, 0), 0);

  const holeAt = (x, y, tol = 0.45) => {
    let best = null, d = tol;
    for (const h of bb.holes) { const e = Math.hypot(h.x - x, h.y - y); if (e < d) { d = e; best = h; } }
    return best;
  };
  const nearestHole = (x, y) => holeAt(x, y, 1e9);
  const turn = (p, r) => { const c = [1, 0, -1, 0][r], s = [0, 1, 0, -1][r]; return [p.x * c - p.y * s, p.x * s + p.y * c]; };
  const isWire = () => entry?.id === "jumper-wires-mm";

  // Swap in a breadboard model (a project may need the full-size one). The twin is rebuilt for the
  // new hole list, keeping its inputs (USB, presence …).
  function useBoard(id) {
    if (bb?.id === id) return;
    if (bb) {
      api.clear();
      group.remove(bb.root);
      bb.root.traverse((o) => o.geometry?.dispose?.());
    }
    const m = CATALOG.find((c) => c.id === id).build();
    decorate(m.parts);
    bb = { id, root: m.root, holes: m.root.userData.holes, top: m.root.userData.top };
    group.add(bb.root);
    if (twin) {
      const old = twin.inputs;
      twin = createTwin({ holes: bb.holes });
      for (const k of ["usb", "mbSwitch", "presence", "arduino", "jumpers", "buttons"]) if (old[k] !== undefined) twin.set(k, old[k]);
    }
  }

  // A two-legged part given only its holes: find the turn (and lead span, for parts that stretch)
  // that puts its legs in them. Returns the closest fit when none is exact.
  function fitTwoPin(e, pins) {
    const names = Object.keys(pins);
    const want = names.map((n) => bb.holes.find((h) => h.name === pins[n]));
    if (want.some((h) => !h)) return null;
    const first = e.build({ ...(e.seated ?? {}) });
    const range = first.root.userData.spans;
    first.root.traverse((o) => o.geometry?.dispose?.());
    const spans = range ? Array.from({ length: range[1] - range[0] + 1 }, (_, i) => range[0] + i) : [null];
    let best = null;
    for (const s of spans) {
      const probe = e.build({ ...(e.seated ?? {}), ...(s ? { span: s } : {}) });
      const ps = probe.root.userData.pins;
      probe.root.traverse((o) => o.geometry?.dispose?.());
      const a = ps.find((q) => q.name === names[0]), b = ps.find((q) => q.name === names[1]);
      if (!a || !b) return null;
      for (let r = 0; r < 4; r++) {
        const [ax, ay] = turn(a, r), [bx, by] = turn(b, r);
        const err = Math.hypot(bx - ax - (want[1].x - want[0].x), by - ay - (want[1].y - want[0].y));
        if (!best || err < best.err) best = { rot: r, span: s, err };
      }
    }
    if (best.err > 0.6) console.warn(`${e.title}: no exact fit for ${names.map((n) => pins[n]).join(", ")}`);
    return best;
  }

  function build(e, opts) {
    const m = e.build({ ...(e.seated ?? {}), ...opts });
    decorate(m.parts);
    const u = m.root.userData;
    return { root: m.root, parts: m.parts, pins: u.pins, tip: u.tip ?? 0, insert: u.insert ?? 5.5, spans: u.spans };
  }
  function pose(root, o, r, tip, insert) {
    root.position.set(o[0], bb.top - insert - tip, -o[1]);
    root.rotation.set(0, (r * Math.PI) / 2, 0);
  }
  function ghostLook(root, ok) {
    root.traverse((o) => {
      if (!o.isMesh) return;
      if (!o.userData.ghostMat) { o.userData.ghostMat = o.material.clone(); o.userData.ghostMat.transparent = true; o.userData.ghostMat.depthWrite = false; }
      o.material = o.userData.ghostMat;
      o.material.opacity = ok ? 0.7 : 0.35;
      o.material.emissive?.set(ok ? 0x000000 : 0x661010);
    });
  }
  function clearGhost() {
    if (ghost) { group.remove(ghost.root); ghost.root.traverse((o) => o.geometry?.dispose?.()); }
    ghost = null;
  }
  function makeGhost() {
    clearGhost();
    if (!entry || isWire()) return;
    ghost = build(entry, span ? { span } : {});
    ghost.root.visible = false;
    group.add(ghost.root);
  }

  // Where would the part go for a pointer at board point (x, y)? Its pins' centre follows the
  // pointer, then the whole part shifts so pin 1 sits exactly in the nearest hole.
  function fit(x, y) {
    const pins = ghost.pins.map((p) => turn(p, rot));
    const cx = pins.reduce((a, p) => a + p[0], 0) / pins.length, cy = pins.reduce((a, p) => a + p[1], 0) / pins.length;
    let o = [x - cx, y - cy];
    const h0 = nearestHole(o[0] + pins[0][0], o[1] + pins[0][1]);
    o = [h0.x - pins[0][0], h0.y - pins[0][1]];
    const holes = pins.map((p) => holeAt(o[0] + p[0], o[1] + p[1]));
    const missing = holes.some((h) => !h);
    const clash = holes.find((h) => h && occupied.has(h.name));
    return { o, holes, ok: !missing && !clash, why: missing ? "a leg misses a hole" : clash ? `${clash.name} is already used` : "" };
  }
  function boardPoint(e) {
    const r = canvas.getBoundingClientRect();
    ndc.set(((e.clientX - r.left) / r.width) * 2 - 1, -((e.clientY - r.top) / r.height) * 2 + 1);
    ray.setFromCamera(ndc, camera);
    plane.constant = -bb.top;
    const p = ray.ray.intersectPlane(plane, new THREE.Vector3());
    return p ? [p.x, -p.z] : null;
  }
  const pinText = (names, holes) => names.map((n, i) => `${n} → ${holes[i]?.name ?? "—"}`).join(" · ");

  function say(text) { readout.textContent = text; }
  function idle() {
    if (!entry) return say("Point at a hole to read its voltage · pick a part on the left to place it");
    if (isWire()) return say(wireStart ? `Wire from ${wireStart.name}: click the other hole · C colour (${WIRE_COLOURS[colour][1]}) · Esc cancel` : `Click two holes to run a ${WIRE_COLOURS[colour][1]} wire · C changes colour`);
    if (!ghost) return say(`${entry.title} doesn't go in a breadboard`);
    say(`${entry.title}: point at the board · R turns it${ghost.spans ? " · [ ] stretch the leads" : ""}`);
  }

  function renderLegend() {
    legend.innerHTML = placed.length
      ? placed.map((p, i) => `<li data-placed="${i}"><b>${String(i + 1).padStart(2, "0")}</b>${p.title} · ${p.device ? `${p.pins.length} header pins, off the board` : p.pins.map((q) => `${q.name} ${q.hole}`).join(", ")}</li>`).join("")
      : `<li><b>—</b>Nothing placed yet. Backspace removes the last part; "Copy layout" gives the hole list as JSON.</li>`;
  }

  function commit(item) {
    placed.push(item);
    item.pins.forEach((p) => occupied.set(p.hole, placed.length - 1));
    dress(item);
    renderLegend();
    sync();
  }
  let quiet = false;
  function sync() { if (quiet) return; twin?.setLayout(api.layout()); panelClock = 1; }
  function removeAt(i) {
    const [item] = placed.splice(i, 1);
    if (!item) return;
    group.remove(item.root);
    item.root.traverse((o) => o.geometry?.dispose?.());
    if (item.extra) group.remove(item.extra);
    occupied.clear();
    placed.forEach((p, k) => p.pins.forEach((q) => occupied.set(q.hole, k)));
    renderLegend();
    sync();
    say(`Removed ${item.title}`);
  }
  function placeAt(e, r, s, firstHole, extra = {}) {
    const saved = { entry, rot, span, ghost };
    entry = e; rot = r; span = s; ghost = build(e, s ? { span: s } : {});
    const pins = ghost.pins.map((p) => turn(p, r));
    const h0 = bb.holes.find((h) => h.name === firstHole);
    const o = [h0.x - pins[0][0], h0.y - pins[0][1]];
    const holes = pins.map((p) => holeAt(o[0] + p[0], o[1] + p[1]));
    pose(ghost.root, o, r, ghost.tip, ghost.insert);
    group.add(ghost.root);
    if (extra.wrong) tint(ghost.root, 0x5a1010);
    commit({ id: e.id, title: extra.title ?? e.title, rot: r, span: s, root: ghost.root, parts: ghost.parts, step: extra.step, wrong: extra.wrong, pins: ghost.pins.map((p, i) => ({ name: p.name, hole: holes[i]?.name ?? "?" })) });
    if (extra.pins) for (const p of placed.at(-1).pins) if (extra.pins[p.name] && extra.pins[p.name] !== p.hole) console.warn(`${extra.title}: ${p.name} landed in ${p.hole}, project says ${extra.pins[p.name]}`);
    ({ entry, rot, span, ghost } = saved);
  }
  function addWire(a, b, c = colour, extra = {}) {
    const m = wire({ a: [a.x, a.y, a.z ?? 0], b: [b.x, b.y, b.z ?? 0], colour: WIRE_COLOURS[c][0], label: `${a.name} to ${b.name}` });
    decorate(m.parts);
    m.root.position.set(0, bb.top, 0);
    group.add(m.root);
    if (extra.wrong) tint(m.root, 0x5a1010);
    commit({ id: "jumper-wire", title: extra.title ?? `${WIRE_COLOURS[c][1][0].toUpperCase()}${WIRE_COLOURS[c][1].slice(1)} wire`, rot: 0, span: null, colour: WIRE_COLOURS[c][1], root: m.root, parts: m.parts, path: m.root.userData.path, step: extra.step, wrong: extra.wrong, pins: [{ name: "end A", hole: a.name }, { name: "end B", hole: b.name }] });
  }
  const terminal = (name) => terminals.get(name) ?? bb.holes.find((h) => h.name === name);
  function tint(root, hex) { root.traverse((o) => { if (o.isMesh) { o.material = o.material.clone(); o.material.emissive?.setHex(hex); } }); }

  // An off-board device (Arduino) sitting on the bench beside the breadboard; its header pins
  // become terminals that wires can run to.
  // lift raises a part that is normally pushed into a board (the radar) so its pins clear the bench.
  function placeDevice(e, name, [x, y], r = 0, lift = 0) {
    const m = e.build();
    decorate(m.parts);
    m.root.position.set(x, TABLE + lift, -y);
    m.root.rotation.set(0, (r * Math.PI) / 2, 0);
    group.add(m.root);
    m.root.updateMatrixWorld(true);
    for (const p of m.root.userData.pins) {
      const w = m.root.localToWorld(at(p.x, p.y, p.z ?? m.root.userData.tip ?? 0));
      terminals.set(`${name} ${p.name}`, { x: w.x, y: -w.z, z: w.y - bb.top, name: `${name} ${p.name}` });
    }
    commit({ id: e.id, title: name, rot: r, span: null, root: m.root, parts: m.parts, device: true, pins: m.root.userData.pins.map((p) => ({ name: p.name, hole: `${name} ${p.name}` })) });
  }

  // One project part (a layout entry) onto the board.
  function placePart(p, extra = {}) {
    const e = CATALOG.find((c) => c.id === p.id);
    if (p.id === "jumper-wire") {
      const c = Math.max(0, WIRE_COLOURS.findIndex(([, n]) => n === (p.colour ?? "red")));
      return addWire(terminal(p.pins["end A"]), terminal(p.pins["end B"]), c, { title: p.title, ...extra });
    }
    let { rot: r = null, span: s = null } = p;
    if (r === null && s === null && Object.keys(p.pins).length === 2) ({ rot: r, span: s } = fitTwoPin(e, p.pins) ?? { rot: 0, span: s });
    const probe = e.build({ ...(e.seated ?? {}), ...(s ? { span: s } : {}) });
    const first = probe.root.userData.pins[0].name;
    probe.root.traverse((o) => o.geometry?.dispose?.());
    placeAt(e, r ?? 0, s, p.pins[first], { title: p.title, pins: p.pins, ...extra });
  }

  const api = {
    active: false,
    open(id) {
      api.active = true;
      useBoard(bb?.id ?? boardId);
      scene.add(group);
      twin ??= createTwin({ holes: bb.holes });
      sync();
      openPanel();
      const box = new THREE.Box3().setFromObject(bb.root).expandByVector(new THREE.Vector3(14, 26, 14));
      const { home, centre } = frame(box);
      camera.position.copy(centre).add(home.clone().sub(centre).multiplyScalar(0.62));
      const t = document.querySelector('[data-c="title"]');
      if (t) t.textContent = "Breadboard layout";
      controls.target.copy(centre);
      renderLegend();
      api.choose(id);
    },
    close() {
      api.active = false;
      panel?.remove();
      panel = null;
      showNet(null);
      clearGhost();
      wireStart = null;
      scene.remove(group);
    },
    choose(id) {
      entry = CATALOG.find((c) => c.id === id) ?? null;
      rot = 0; wireStart = null;
      span = entry?.span ?? null;
      makeGhost();
      if (ghost && !ghost.pins) clearGhost();
      document.querySelectorAll(".catalog button").forEach((b) => b.setAttribute("aria-current", String(b.dataset.id === id)));
      idle();
    },
    pointer(e) {
      const p = boardPoint(e);
      lastHit = p;
      if (!p) return;
      if (!entry) {
        const h = holeAt(p[0], p[1], 1.3);
        inspect = h?.name ?? null;
        showNet(inspect ? twin.netOf(inspect) : null);
        if (!h) return idle();
        const net = twin.netOf(h.name);
        say(`${h.name} · ${net.v === null ? "nothing connected" : fmtV(net.v)} · ${net.label}`);
        return;
      }
      if (isWire()) {
        const h = nearestHole(p[0], p[1]);
        if (wireStart) {
          if (ghost) clearGhost();
          const m = wire({ a: [wireStart.x, wireStart.y], b: [h.x, h.y], colour: WIRE_COLOURS[colour][0] });
          ghost = { root: m.root };
          m.root.position.set(0, bb.top, 0);
          ghostLook(m.root, !occupied.has(h.name));
          group.add(m.root);
        }
        say(wireStart ? `Wire ${wireStart.name} → ${h.name} · click to place` : `Start the wire at ${h.name}${occupied.has(h.name) ? " (already used)" : ""}`);
        return;
      }
      if (!ghost) return;
      const f = fit(p[0], p[1]);
      ghost.root.visible = true;
      pose(ghost.root, f.o, rot, ghost.tip, ghost.insert);
      ghostLook(ghost.root, f.ok);
      say(`${entry.title} · ${pinText(ghost.pins.map((q) => q.name), f.holes)}${f.ok ? " · click to place" : ` · ${f.why}`}`);
    },
    place(e) {
      const p = boardPoint(e);
      if (!p || !entry) return;
      if (isWire()) {
        const h = nearestHole(p[0], p[1]);
        if (occupied.has(h.name)) return say(`${h.name} is already used`);
        if (!wireStart) { wireStart = h; return idle(); }
        if (h.name === wireStart.name) return;
        clearGhost();
        addWire(wireStart, h);
        wireStart = null;
        colour = (colour + 1) % WIRE_COLOURS.length;
        return idle();
      }
      if (!ghost) return;
      const f = fit(p[0], p[1]);
      if (!f.ok) return say(`Can't place here: ${f.why}`);
      const root = ghost.root;
      root.traverse((o) => { if (o.isMesh && o.userData.ghostMat) { o.material = o.userData.ghostMat.clone(); o.material.transparent = false; o.material.opacity = 1; o.material.depthWrite = true; o.material.emissive?.set(0x000000); } });
      commit({ id: entry.id, title: entry.title, rot, span, root, parts: ghost.parts, pins: ghost.pins.map((q, i) => ({ name: q.name, hole: f.holes[i].name })) });
      say(`Placed ${entry.title}: ${placed.at(-1).pins.map((q) => `${q.name} → ${q.hole}`).join(" · ")}`);
      ghost = null;
      makeGhost();
    },
    key(e) {
      const k = e.key;
      if (k === "r" || k === "R") { rot = (rot + 1) % 4; if (lastHit) api.pointer(lastEvent); }
      else if ((k === "[" || k === "]") && ghost?.spans) {
        span = Math.min(ghost.spans[1], Math.max(ghost.spans[0], (span ?? entry.span) + (k === "]" ? 1 : -1)));
        makeGhost();
        if (lastEvent) api.pointer(lastEvent);
      } else if (k === "c" || k === "C") { colour = (colour + 1) % WIRE_COLOURS.length; idle(); }
      else if (k === "Backspace" || k === "Delete") { api.undo(); }
      else if (k === "Escape") { wireStart = null; entry = null; clearGhost(); document.querySelectorAll(".catalog button").forEach((b) => b.setAttribute("aria-current", "false")); idle(); }
      else if (k === "p" || k === "P") { twin.set("usb", !twin.inputs.usb); panelClock = 1; }
      else if (k === "h" || k === "H") { twin.set("presence", !twin.inputs.presence); panelClock = 1; }
      else return;
      e.preventDefault();
    },
    undo() { removeAt(placed.length - 1); },
    clear() { while (placed.length) api.undo(); terminals.clear(); },
    // Lay out a Bench Buddy project as far as the given steps, with its bench inputs.
    loadProject(id, steps = Object.keys(PROJECTS[id].steps), inputs = {}) {
      project = { id, ...PROJECTS[id] };
      quiet = true;
      useBoard(project.board ?? bb?.id ?? boardId);
      api.clear();
      for (const d of project.devices) placeDevice(CATALOG.find((c) => c.id === d.id), d.name, d.at, d.rot);
      for (const p of project.base) placePart(p);
      for (const sid of steps) for (const p of project.steps[sid]?.place ?? []) placePart(p, { step: sid });
      const ins = { ...project.inputs };
      for (const sid of steps) Object.assign(ins, project.steps[sid]?.inputs ?? {});
      Object.assign(ins, inputs);
      for (const [k, v] of Object.entries(ins)) twin.set(k, v);
      quiet = false;
      sync();
      const box = new THREE.Box3().setFromObject(group);
      const { home, centre } = frame(box.expandByVector(new THREE.Vector3(4, 10, 4)));
      camera.position.copy(centre).add(home.clone().sub(centre).multiplyScalar(0.55));
      controls.target.copy(centre);
      say(project.title);
    },
    // A step happened on the real bench: place its parts where they belong, or (mode "wrong")
    // where vision saw them, shifted to that row; "remove" takes them out again.
    applyStep(sid, mode = "pass", row = null) {
      if (!project) return;
      const step = project.steps[sid];
      if (!step) return;
      for (let i = placed.length - 1; i >= 0; i--) if (placed[i].step === sid) removeAt(i);
      if (mode !== "remove") for (const p of step.place ?? []) {
        if (mode === "wrong" && step.row && row) placePart(shiftRows(p, row - step.row), { step: sid, wrong: true, title: `${p.title} (vision saw row ${row})` });
        else placePart(p, { step: sid });
      }
      if (mode === "pass") for (const [k, v] of Object.entries(step.inputs ?? {})) twin.set(k, v);
      sync();
    },
    // Show a whole layout as it is right now (what vision sees on the real bench): devices beside the
    // board, then every part. Rebuilt from scratch each time; the camera is framed only when asked.
    //   { board?, devices: [{ id, name, at: [x, y], rot }], parts: [layout parts], inputs: { usb, presence … } }
    showLayout(next, { reframe = false } = {}) {
      project = null;
      quiet = true;
      useBoard(next.board ?? bb?.id ?? boardId);
      api.clear();
      for (const d of next.devices ?? []) placeDevice(CATALOG.find((c) => c.id === d.id), d.name, d.at, d.rot ?? 0, d.lift ?? 0);
      for (const p of next.parts ?? []) {
        try { placePart(p, { wrong: p.wrong }); } catch (err) { console.warn("couldn't place", p, err); }
      }
      for (const [k, v] of Object.entries(next.inputs ?? {})) twin.set(k, v);
      quiet = false;
      sync();
      if (reframe) {                                   // on the breadboard itself (the laptop prop is far off)
        const box = new THREE.Box3().setFromObject(bb.root).expandByVector(new THREE.Vector3(6, 12, 18));
        const { home, centre } = frame(box);
        camera.position.copy(centre).add(home.clone().sub(centre).multiplyScalar(0.9));
        controls.target.copy(centre);
      }
    },
    get project() { return project; },
    layout() {
      return { board: bb?.id ?? boardId, parts: placed.map((p) => ({ id: p.id, title: p.title, rotation: p.rot * 90, span: p.span ?? undefined, colour: p.colour, step: p.step, wrong: p.wrong || undefined, device: p.device || undefined, pins: Object.fromEntries(p.pins.map((q) => [q.name, q.hole])) })) };
    },
    copyLayout() {
      const text = JSON.stringify(api.layout(), null, 2);
      navigator.clipboard?.writeText(text).then(() => say(`Copied the layout of ${placed.length} parts as JSON`), () => say("Couldn't reach the clipboard; the layout is in the console"));
      console.log(text);
    },
    // The circuit from radar-led-demo.md: radar IO → 1 kΩ → LED → GND, power from the MB102.
    demo() {
      return api.loadProject("radar-led", undefined, { usb: true });
    },
  };
  // ── Live simulation ───────────────────────────────────────────────────────────────────
  // Per placed item: find what lights up (LED lens, power LED) and set up flow dots on wires.
  function dress(item) {
    item.glow = [];
    item.power = [];
    item.root.traverse((o) => {
      if (!o.isMesh) return;
      if (o.userData.glow) { o.material = o.material.clone(); item.glow.push(o); }
      if (o.userData.powerLed) { o.material = o.material.clone(); item.power.push(o); }
    });
    if (item.glow.length) {
      item.light = new THREE.PointLight(0xff3020, 0, 60, 2);
      item.light.position.copy(at(0, 0, 6));
      item.root.add(item.light);
    }
    if (item.path) {
      const curve = new THREE.CatmullRomCurve3(item.path.map((q) => at(...q)));
      const dotMat = new THREE.MeshBasicMaterial({ color: 0xfff1a0 });
      item.flow = { curve, phase: 0, dots: Array.from({ length: 6 }, () => { const m = new THREE.Mesh(new THREE.SphereGeometry(0.55, 10, 8), dotMat); m.visible = false; item.root.add(m); return m; }) };
    }
    if (item.id === "breadboard-power-mb102") {
      // USB cable from the socket on the module's long edge to a laptop off the end of the bench.
      item.root.updateMatrixWorld(true);
      const local = (x, y, z) => item.root.localToWorld(at(x, y, z)).sub(group.position);
      const socket = local(-7, -18.6, 3.5), out = local(-7, -32, 3.5), floor = -0.8;
      const dir = out.clone().sub(socket).setY(0).normalize();
      const pts = [socket, out, socket.clone().addScaledVector(dir, 26).setY(floor + 1.6), socket.clone().addScaledVector(dir, 60).setY(floor + 1.6), socket.clone().addScaledVector(dir, 86).setY(floor + 6)];
      const extra = new THREE.Group();
      extra.add(new THREE.Mesh(new THREE.TubeGeometry(new THREE.CatmullRomCurve3(pts), 60, 1.6, 10), new THREE.MeshStandardMaterial({ color: 0x1d1d1f, roughness: 0.6 })));
      const plug = new THREE.Mesh(new THREE.BoxGeometry(12, 5, 12), new THREE.MeshStandardMaterial({ color: 0x2a2a2c, roughness: 0.5 }));
      plug.position.copy(socket.clone().addScaledVector(dir, 6));
      plug.lookAt(socket.clone().addScaledVector(dir, 20));
      extra.add(plug);
      const laptop = new THREE.Mesh(new THREE.BoxGeometry(70, 6, 50), new THREE.MeshStandardMaterial({ color: 0x9da3a8, roughness: 0.4, metalness: 0.6 }));
      laptop.position.copy(socket.clone().addScaledVector(dir, 120).setY(floor + 3));
      laptop.lookAt(laptop.position.clone().add(dir));
      extra.add(laptop);
      extra.userData.cable = true;
      item.extra = extra;
      group.add(extra);
    }
  }

  // Hover highlight: a green disc on every hole of the net under the pointer.
  let discs = null;
  function showNet(net) {
    if (!discs) {
      discs = new THREE.InstancedMesh(new THREE.CircleGeometry(0.95, 20), new THREE.MeshBasicMaterial({ color: 0x3ccf72, transparent: true, opacity: 0.85, depthWrite: false }), 400);
      discs.rotation.x = -Math.PI / 2;
      discs.count = 0;
      group.add(discs);
    }
    const holes = net?.holes ?? [];
    const m = new THREE.Matrix4();
    holes.slice(0, 400).forEach((name, i) => {
      const h = bb.holes.find((x) => x.name === name);
      m.makeTranslation(h.x, h.y, bb.top + 0.05);
      discs.setMatrixAt(i, m);
    });
    discs.count = Math.min(holes.length, 400);
    discs.instanceMatrix.needsUpdate = true;
  }

  function openPanel() {
    panel?.remove();
    panel = document.createElement("section");
    panel.className = "sim";
    panel.innerHTML = `<div class="sim-controls">
      <button data-sim="usb">USB power (P)</button>
      <button data-sim="switch">MB102 switch</button>
      <button data-sim="left">Back rails: 5V</button>
      <button data-sim="right">Front rails: 5V</button>
      <button data-sim="presence">Person in front of radar (H)</button>
    </div><div class="sim-note" hidden></div><div class="sim-body"></div>`;
    if (panelHost) panelHost.append(panel); else document.querySelector(".bar").after(panel);
    panel.addEventListener("click", (e) => {
      const k = e.target.closest("button")?.dataset.sim;
      if (!k) return;
      const cycle = (v) => ({ "5V": "3V3", "3V3": "OFF", OFF: "5V" })[v ?? "5V"];
      if (k === "usb") twin.set("usb", !twin.inputs.usb);
      if (k === "switch") twin.set("mbSwitch", twin.inputs.mbSwitch === false);
      if (k === "presence") twin.set("presence", !twin.inputs.presence);
      if (k === "left" || k === "right") twin.set("jumpers", { [k]: cycle(twin.inputs.jumpers[k]) });
      panelClock = 1;
    });
  }
  function renderPanel(r) {
    if (!panel) return;
    const inp = twin.inputs;
    const set = (k, on, text) => { const b = panel.querySelector(`[data-sim="${k}"]`); b.setAttribute("aria-pressed", String(on)); if (text) b.textContent = text; };
    set("usb", inp.usb);
    set("switch", inp.mbSwitch !== false);
    set("left", inp.jumpers.left !== "OFF", `Back rails: ${inp.jumpers.left}`);
    set("right", inp.jumpers.right !== "OFF", `Front rails: ${inp.jumpers.right}`);
    set("presence", inp.presence);
    const esc = (t) => String(t).replace(/[&<>]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;" })[c]);
    // Wires show their current as moving dots, so the list keeps to parts and devices.
    const parts = r.parts.filter((p, i) => placed[i]?.id !== "jumper-wire");
    const nets = r.nets.filter((n) => n.holes.length || n.pins.length > 1);
    panel.querySelector(".sim-body").innerHTML =
      (r.warnings.length ? `<ul class="sim-warn">${r.warnings.map((w) => `<li>${esc(w)}</li>`).join("")}</ul>` : "") +
      `<div class="sim-cols"><div><h3>Parts</h3><ul>${parts.map((p) => `<li><b>${esc(p.title)}</b> ${esc(p.text)}</li>`).join("") || "<li>Nothing placed</li>"}</ul></div>` +
      `<div><h3>Nets</h3><ul>${nets.map((n) => `<li><b>${fmtV(n.v)}</b> ${esc(n.label)}</li>`).join("") || "<li>No nets yet</li>"}</ul></div></div>`;
  }

  api.tick = (dt) => {
    if (!api.active || !twin) return;
    const r = twin.step(Math.min(dt, 0.05));
    placed.forEach((item, i) => {
      const rep = r.parts[i];
      if (!rep) return;
      if (item.glow.length) {
        const g = rep.glow ?? 0;
        for (const m of item.glow) { m.material.emissive.copy(glowColour).multiplyScalar(0.25 + 2.2 * g); m.material.opacity = 0.55 + 0.35 * g; m.material.emissive.multiplyScalar(g > 0.004 ? 1 : 0); }
        item.light.intensity = 900 * g;
      }
      if (item.power.length) {
        const on = item.id === "arduino-uno" ? twin.inputs.arduino !== false : twin.inputs.usb && twin.inputs.mbSwitch !== false;
        for (const m of item.power) m.material.emissive.set(on ? 0x2aff70 : 0x000000);
      }
      if (item.extra?.userData.cable) item.extra.visible = twin.inputs.usb;
      if (item.flow) {
        const I = rep.flow ?? 0, mag = Math.abs(I);
        const moving = mag > 2e-6;
        const speed = moving ? Math.min(1.2, 0.08 * Math.log10(mag / 1e-6)) : 0;
        item.flow.phase = (item.flow.phase + Math.sign(I) * speed * dt + 1) % 1;
        item.flow.dots.forEach((d, k) => {
          d.visible = moving;
          if (moving) d.position.copy(item.flow.curve.getPointAt((item.flow.phase + k / item.flow.dots.length) % 1));
        });
      }
    });
    const pulse = 0.5 + 0.5 * Math.sin(performance.now() / 180);
    placed.forEach((item) => {
      const on = !!suspectText && suspectText.includes(item.title);
      if (!on && !item.flagged) return;
      item.flagged = on;
      item.root.traverse((o) => { if (o.isMesh && o.userData.base && !item.glow.includes(o)) o.material.emissive.copy(on ? new THREE.Color(0xff2020).multiplyScalar(0.15 + 0.35 * pulse) : item.wrong ? new THREE.Color(0x5a1010) : o.userData.base); });
    });
    panelClock += dt;
    if (panelClock > 0.25) { panelClock = 0; renderPanel(r); if (inspect) showNet(twin.netOf(inspect)); }
  };
  Object.defineProperty(api, "twin", { get: () => twin });
  // A message from the live follower (diagnosis, blink-rate comparison), shown above the parts.
  api.note = (html) => { const n = panel?.querySelector(".sim-note"); if (!n) return; n.innerHTML = html; n.hidden = !html; };
  // The part a diagnosis blames pulses red until the bench measures healthy again.
  let suspectText = null;
  api.suspect = (text) => { suspectText = text; };

  let lastEvent = null;
  const pointer = api.pointer;
  api.pointer = (e) => { lastEvent = e; pointer(e); };
  return api;
}
