// The breadboard twin as a widget for the Bench Buddy UI (bundled to ui/vendor/twin.bundle.mjs by build.mjs).
//
//   const twin = mountTwin(el, { onStatus })
//   twin.applyVision(state)   vision.state() / the SSE "board" event: redraw what is on the real board, re-simulate
//   twin.applyLog(line)       tutor log lines: each step's instruction highlights where it goes; a radar or a
//                             resistor value mentioned shapes the layout; "red is V …" names the radar leads; a
//                             passed power step powers the rails
//   twin.setPresence(on)      someone in front of the radar (the sim's IO goes high)
//
// onStatus({ phase, rows, target, simLit, realLit, agree, unplaced }) runs whenever any of that changes: vision's
// live phase (calibrating, hands, looking, ready), the open step's target, and the simulated vs the real LED.
import * as THREE from "three";
import { OrbitControls } from "three/addons/controls/OrbitControls.js";
import { CATALOG } from "./catalog.js";
import { createBoard } from "./board.js";
import { fromVision, leadsFrom, targetsFrom, twinHole, LIVE_BOARD } from "./from-vision.js";

export function mountTwin(el, { onStatus = () => {} } = {}) {
  el.classList.add("twin");
  el.innerHTML = `<canvas class="twin-canvas" tabindex="0" aria-label="3D simulation of the breadboard"></canvas>
    <p class="twin-readout" aria-live="polite"></p><ol class="twin-legend" hidden></ol><div class="twin-sim"></div>`;
  const canvas = el.querySelector("canvas");
  const readout = el.querySelector(".twin-readout");
  const legend = el.querySelector(".twin-legend");
  const simHost = el.querySelector(".twin-sim");

  const renderer = new THREE.WebGLRenderer({ canvas, antialias: true, alpha: true });
  renderer.setPixelRatio(Math.min(devicePixelRatio, 2));
  renderer.outputColorSpace = THREE.SRGBColorSpace;
  renderer.toneMapping = THREE.ACESFilmicToneMapping;
  renderer.shadowMap.enabled = true;
  renderer.shadowMap.type = THREE.PCFSoftShadowMap;
  renderer.setClearColor(0x000000, 0);           // the cutting mat shows through

  const scene = new THREE.Scene();
  const camera = new THREE.PerspectiveCamera(28, 16 / 10, 0.1, 4000);
  scene.add(new THREE.HemisphereLight(0xffffff, 0x9a9aa2, 1.6));
  const key = new THREE.DirectionalLight(0xffffff, 2.4);
  key.castShadow = true;
  key.shadow.mapSize.set(2048, 2048);
  key.shadow.bias = -0.0005;
  scene.add(key, key.target);
  const fill = new THREE.DirectionalLight(0xffffff, 0.7);
  scene.add(fill);
  const ground = new THREE.Mesh(new THREE.PlaneGeometry(1, 1), new THREE.ShadowMaterial({ opacity: 0.3 }));
  ground.rotation.x = -Math.PI / 2;
  ground.receiveShadow = true;
  scene.add(ground);
  const controls = new OrbitControls(camera, canvas);
  controls.enableDamping = true;
  controls.maxPolarAngle = Math.PI / 2 - 0.05;
  const lineMat = new THREE.LineBasicMaterial({ color: 0x000000, transparent: true, opacity: 0.5 });

  // Same look as the parts gallery: outlines on every solid, per-part materials so parts can glow.
  function decorate(parts) {
    for (const p of parts) {
      p.userData.meshes = [];
      p.traverse((o) => {
        if (!o.isMesh || o.userData.label || o.userData.outlined) return;
        o.castShadow = o.receiveShadow = true;
        o.material = o.material.clone();
        o.userData.base = o.material.emissive.clone();
        o.userData.outlined = true;
        const edges = new THREE.LineSegments(new THREE.EdgesGeometry(o.geometry, 32), lineMat);
        edges.userData.outline = true;
        edges.raycast = () => {};
        o.add(edges);
        p.userData.meshes.push(o);
      });
    }
  }
  function frameOn(reach) {
    const centre = reach.getCenter(new THREE.Vector3());
    const radius = Math.max(reach.getSize(new THREE.Vector3()).length() / 2, 4);
    const dist = radius / Math.sin(THREE.MathUtils.degToRad(camera.fov / 2)) * 1.05;
    const home = centre.clone().add(new THREE.Vector3(0.15, 0.95, 0.75).normalize().multiplyScalar(dist));
    camera.near = dist / 100;
    camera.far = dist * 20;
    camera.updateProjectionMatrix();
    controls.minDistance = radius * 0.4;
    controls.maxDistance = dist * 4;
    controls.target.copy(centre);
    camera.position.copy(home);
    const s = radius * 2.2;
    Object.assign(key.shadow.camera, { left: -s, right: s, top: s, bottom: -s, near: 0.1, far: dist * 6 });
    key.shadow.camera.updateProjectionMatrix();
    key.position.copy(centre).add(new THREE.Vector3(0.4, 1, 0.55).multiplyScalar(dist));
    key.target.position.copy(centre);
    fill.position.copy(centre).add(new THREE.Vector3(-0.8, 0.4, -0.4).multiplyScalar(dist));
    ground.scale.setScalar(radius * 40);
    ground.position.set(centre.x, reach.min.y - 0.2, centre.z);
    return { home, centre };
  }

  const board = createBoard({ THREE, scene, camera, controls, canvas, CATALOG, decorate, frame: frameOn, readout, legend, hold: () => {}, boardId: LIVE_BOARD, panelHost: simHost });
  board.open(null);
  board.twin.set("usb", false);                      // the rails are dead until a power step passes (or the LED lights)
  canvas.addEventListener("pointermove", (e) => { if (!e.buttons) board.pointer(e); });   // hover a hole: its voltage and net

  // Live state: what vision last saw, plus what the conversation told us.
  const live = { vision: null, sig: "", usb: false, presence: false, leads: {}, radar: false, ohms: 1000,
    framed: false, unplaced: [], activity: { phase: "none" }, steps: [], target: null };   // "none": no vision state yet
  let last = "";

  // The sim panel's buttons (USB, presence) change the twin directly; keep them across redraws.
  const pull = () => { if (board.twin) { live.usb = !!board.twin.inputs.usb; live.presence = !!board.twin.inputs.presence; } };
  function redraw() {
    if (!live.vision) return;
    const { layout, unplaced } = fromVision(live.vision, live);
    live.unplaced = unplaced;
    board.showLayout(layout, { reframe: !live.framed });
    board.twin?.step(0.02);                          // settle the circuit now, so the status is right before the next frame
    live.framed = true;
    readout.textContent = "";                        // showLayout narrates its clear/place; the readout is for hover
    remark();
  }
  function remark() {
    const a = live.activity;
    board.mark({ look: a.phase === "looking" ? { rows: a.rows ?? [], holes: (a.holes ?? []).map(twinHole).filter(Boolean) } : null, target: live.target });
  }
  const simLed = () => {
    const parts = board.twin?.results?.parts ?? [];
    const led = parts.find((p) => p.title === "LED");
    return led ? (led.glow ?? 0) > 0.05 : null;
  };
  function report() {
    const simLit = simLed();
    const realLit = live.vision ? !!live.vision.led : null;
    const a = live.activity;
    const key = JSON.stringify([simLit, realLit, a.phase, a.rows, live.target]);
    if (key === last) return;
    last = key;
    const agree = simLit === null || realLit === null || simLit === realLit;
    board.note(agree ? "" : simLit
      ? "<b>The simulation lights the LED, but the camera sees it dark.</b> Check the LED's direction and that its legs share rows with the resistor and the ground wire."
      : "<b>The camera sees the LED lit, but the simulation doesn't.</b> Vision may have misread a hole; the board view shows where it thinks each part is.");
    onStatus({ simLit, realLit, agree, phase: a.phase, rows: a.rows ?? [], target: live.target, unplaced: live.unplaced });
  }

  // What the conversation says about the build: a radar in it, the resistor's value, which step is open.
  const RADAR_WORDS = /\b(radar|ld2402|hlk)\b/i;
  const POWER_STEP = /\b(power the|usb|5 ?volts?|plug in the power)\b/i;
  const PRESENCE_STEP = /\b(walk|in front of the radar|wave)\b/i;
  function ohmsFrom(text) {
    const m = /(\d+(?:\.\d+)?)\s*(k|kilo|m|meg)?\s*(?:ohms?|Ω)?\s*resistor|(\d+(?:\.\d+)?)\s*(kilo|mega)?ohm/i.exec(text ?? "");
    if (!m) return null;
    const v = +(m[1] ?? m[3]), pre = (m[2] ?? m[4] ?? "").toLowerCase();
    return v * (pre.startsWith("k") ? 1e3 : pre.startsWith("m") ? 1e6 : 1);
  }

  function resize() {
    const w = canvas.clientWidth, h = canvas.clientHeight, pr = renderer.getPixelRatio();
    if (w && h && (canvas.width !== Math.round(w * pr) || canvas.height !== Math.round(h * pr))) {
      renderer.setSize(w, h, false);
      camera.aspect = w / h;
      camera.updateProjectionMatrix();
    }
  }
  let then = performance.now(), clock = 0, raf = 0;
  function frame(now) {
    const dt = Math.min((now - then) / 1000, 1 / 30);
    then = now;
    resize();
    board.tick(dt);
    if ((clock += dt) > 0.3) { clock = 0; report(); }
    controls.update();
    renderer.render(scene, camera);
    raf = requestAnimationFrame(frame);
  }
  raf = requestAnimationFrame(frame);

  const api = {
    board,
    get twin() { return board.twin; },
    // vision.state(): redraw only when the part list or the LED changed; activity just moves the highlights.
    applyVision(state) {
      if (!state || !Array.isArray(state.board)) return;
      pull();
      live.vision = state;
      if (state.activity) live.activity = state.activity;
      if (state.board.some((p) => p.part === "radar")) live.radar = true;
      // A lit LED on the bench means it's powered and someone is there: let the simulation agree.
      if (state.led) { live.usb = true; live.presence = true; }
      const sig = JSON.stringify([state.board, !!state.led]);
      if (sig !== live.sig || !live.framed) { live.sig = sig; redraw(); } else remark();
      report();
    },
    applyLog(line) {
      if (!line) return;
      pull();
      if (/^Hi, I'm Bench Buddy/.test(line.said ?? "")) {
        Object.assign(live, { usb: false, presence: false, leads: {}, radar: false, ohms: 1000, steps: [], target: null });
        redraw();
        return remark();
      }
      const text = [line.said, line.heard, line.goal, line.use_case].filter(Boolean).join(" ");
      let changed = false;
      if (RADAR_WORDS.test(text) && !live.radar) live.radar = changed = true;
      if (Array.isArray(line.parts)) {
        const r = line.parts.find((p) => p?.type === "resistor" && p.value);
        if (r) { live.ohms = +r.value; changed = true; }
      }
      if (line.heard) {
        const o = ohmsFrom(line.heard);
        if (o) { live.ohms = o; changed = true; }
        const leads = leadsFrom(line.heard);
        if (Object.keys(leads).length) { Object.assign(live.leads, leads); changed = true; }
      }
      if (Array.isArray(line.plan)) {
        live.steps = line.plan;
        if (!live.radar && line.plan.some((s) => RADAR_WORDS.test(s.say))) live.radar = changed = true;
      }
      // A step opens when its instruction is said: show where it goes. It closes when its check passes.
      const open = line.said && live.steps.find((s) => s.say === line.said);
      if (open) { live.target = { ...targetsFrom(open.say), step: open.id }; remark(); }
      if (line.step && line.result === "pass") {
        const done = live.steps.find((s) => s.id === line.step);
        if (done && POWER_STEP.test(done.say)) api.setUsb(true);
        if (done && PRESENCE_STEP.test(done.say)) api.setPresence(true);
        if (live.target?.step === line.step) { live.target = null; remark(); }
      }
      if (line.transition === "DONE") { live.target = null; remark(); }
      if (changed) redraw();
      report();
    },
    setPresence(on) { live.presence = !!on; board.twin?.set("presence", live.presence); },
    setUsb(on) { live.usb = !!on; board.twin?.set("usb", live.usb); },
    dispose() { cancelAnimationFrame(raf); renderer.dispose(); el.innerHTML = ""; },
  };
  return api;
}
