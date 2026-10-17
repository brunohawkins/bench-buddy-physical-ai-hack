// The breadboard twin as a widget for the Bench Buddy UI (bundled to ui/vendor/twin.bundle.mjs by build.mjs).
//
//   const twin = mountTwin(el, { onStatus })
//   twin.applyVision(state)   vision.state() / the SSE "board" event: redraw what is on the real board, re-simulate
//   twin.applyLog(line)       tutor log lines: the usb step powers the rails, "red is V …" names the radar leads
//   twin.setPresence(on)      someone in front of the radar (the sim's IO goes high)
//   twin.followScript(id)     follow a scripted project's log lines instead (the UI's 555 demo): live.js
//
// onStatus({ simLit, realLit, agree, unplaced, parts }) runs whenever the simulated LED or vision's LED changes,
// so the UI can say when the bench and the simulation disagree.
import * as THREE from "three";
import { OrbitControls } from "three/addons/controls/OrbitControls.js";
import { CATALOG } from "./catalog.js";
import { createBoard } from "./board.js";
import { fromVision, leadsFrom, LIVE_BOARD } from "./from-vision.js";
import { follow } from "./live.js";

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
  board.twin.set("usb", false);                      // the rails are dead until the tutor's usb step
  canvas.addEventListener("pointermove", (e) => { if (!e.buttons) board.pointer(e); });   // hover a hole: its voltage and net

  // Live state: what vision last saw, plus what the conversation told us.
  const live = { vision: null, usb: false, presence: false, leads: {}, framed: false, unplaced: [] };
  let last = { simLit: null, realLit: null };
  let script = null;                                 // live.js follower when replaying a scripted project

  // The sim panel's buttons (USB, presence) change the twin directly; keep them across redraws.
  const pull = () => { if (board.twin) { live.usb = !!board.twin.inputs.usb; live.presence = !!board.twin.inputs.presence; } };
  function redraw() {
    if (!live.vision) return;
    const { layout, unplaced } = fromVision(live.vision, { usb: live.usb, presence: live.presence, leads: live.leads });
    live.unplaced = unplaced;
    board.showLayout(layout, { reframe: !live.framed });
    live.framed = true;
    readout.textContent = "";                        // showLayout narrates its clear/place; the readout is for hover
  }
  const simLed = () => {
    const parts = board.twin?.results?.parts ?? [];
    const led = parts.find((p) => p.title === "LED");
    return led ? (led.glow ?? 0) > 0.05 : null;
  };
  function report() {
    const simLit = simLed();
    const realLit = live.vision ? !!live.vision.led : null;
    if (simLit === last.simLit && realLit === last.realLit) return;
    last = { simLit, realLit };
    const agree = simLit === null || realLit === null || simLit === realLit;
    board.note(agree ? "" : simLit
      ? "<b>The simulation lights the LED, but the camera sees it dark.</b> Check the LED's direction and that its legs share rows with the resistor and the ground wire."
      : "<b>The camera sees the LED lit, but the simulation doesn't.</b> Vision may have misread a hole; the board view shows where it thinks each part is.");
    onStatus({ simLit, realLit, agree, unplaced: live.unplaced, parts: board.layout().parts.length });
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
    applyVision(state) {
      if (!state || !Array.isArray(state.board)) return;
      pull();
      live.vision = state;
      // A lit LED on the bench means it's powered and someone is there: let the simulation agree.
      if (state.led) { live.usb = true; live.presence = true; }
      redraw();
    },
    applyLog(line) {
      if (!line) return;
      if (script) return script.handle(line);
      if (/^Hi, I'm Bench Buddy/.test(line.said ?? "")) {
        Object.assign(live, { usb: false, presence: false, leads: {} });
        redraw();
      }
      pull();
      if (line.heard) {
        const leads = leadsFrom(line.heard);
        if (Object.keys(leads).length) { Object.assign(live.leads, leads); redraw(); }
      }
      if (line.step === "usb" && line.result === "pass") api.setUsb(true);
      if (line.step === "finish" && line.result === "pass") api.setPresence(true);
    },
    setPresence(on) { live.presence = !!on; board.twin?.set("presence", live.presence); },
    setUsb(on) { live.usb = !!on; board.twin?.set("usb", live.usb); },
    followScript(projectId) { live.vision = null; live.framed = true; script = follow(board, { url: null, projectId }); },
    dispose() { cancelAnimationFrame(raf); renderer.dispose(); el.innerHTML = ""; },
  };
  return api;
}
