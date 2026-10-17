// Parts gallery: pick a component, rotate it 360°, take it apart, point at a part, move parts,
// export it as GLB. Bundled with three.js into index.html by build.mjs.
import * as THREE from "three";
import { OrbitControls } from "three/addons/controls/OrbitControls.js";
import { TransformControls } from "three/addons/controls/TransformControls.js";
import { GLTFExporter } from "three/addons/exporters/GLTFExporter.js";
import { CATALOG } from "./catalog.js";
import { createBoard } from "./board.js";
import { follow } from "./live.js";

const canvas = document.querySelector(".stage");
const readout = document.querySelector("[data-readout]");
const title = document.querySelector('[data-c="title"]');
const still = matchMedia("(prefers-reduced-motion: reduce)");
const html = document.documentElement;
try { const saved = localStorage.getItem("parts-theme"); if (saved) html.dataset.theme = saved; } catch {}

const renderer = new THREE.WebGLRenderer({ canvas, antialias: true, preserveDrawingBuffer: true });
renderer.setPixelRatio(Math.min(devicePixelRatio, 2));
renderer.outputColorSpace = THREE.SRGBColorSpace;
renderer.toneMapping = THREE.ACESFilmicToneMapping;
renderer.shadowMap.enabled = true;
renderer.shadowMap.type = THREE.PCFSoftShadowMap;

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
const ground = new THREE.Mesh(new THREE.PlaneGeometry(1, 1), new THREE.ShadowMaterial({ opacity: 0.35 }));
ground.rotation.x = -Math.PI / 2;
ground.receiveShadow = true;
scene.add(ground);

const controls = new OrbitControls(camera, canvas);
controls.enableDamping = true;
controls.minPolarAngle = 0;
controls.maxPolarAngle = Math.PI;
controls.autoRotate = !still.matches;
controls.autoRotateSpeed = 1.2;
const mover = new TransformControls(camera, canvas);
mover.setSize(0.7);
mover.addEventListener("dragging-changed", (e) => { controls.enabled = !e.value; });
scene.add(mover);

const lineMat = new THREE.LineBasicMaterial({ color: 0x000000, transparent: true, opacity: 0.55 });
const litLine = new THREE.LineBasicMaterial({ color: 0xffffff });
const button = (act) => document.querySelector(`[data-act="${act}"]`);

let current = null; // { entry, root, groups, parts, assemblies, size, home }
let springs = [], apart = false, hover = -1, picked = -1, DEFAULT = "";

// Outlines on every solid (the anatomy look), and per-part materials so one part can light up.
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

// Point the camera, lights and shadow at a box; returns the camera's home position.
function frameOn(reach) {
  const centre = reach.getCenter(new THREE.Vector3());
  const radius = Math.max(reach.getSize(new THREE.Vector3()).length() / 2, 4);
  const dist = radius / Math.sin(THREE.MathUtils.degToRad(camera.fov / 2)) * 1.05;
  const home = centre.clone().add(new THREE.Vector3(0.62, 0.5, 0.72).normalize().multiplyScalar(dist));
  camera.near = dist / 100;
  camera.far = dist * 20;
  camera.updateProjectionMatrix();
  controls.minDistance = radius * 0.6;
  controls.maxDistance = dist * 5;
  controls.target.copy(centre);
  camera.position.copy(home);
  const s = radius * 2.2;
  Object.assign(key.shadow.camera, { left: -s, right: s, top: s, bottom: -s, near: 0.1, far: dist * 6 });
  key.shadow.camera.updateProjectionMatrix();
  key.position.copy(centre).add(new THREE.Vector3(0.4, 1, 0.55).multiplyScalar(dist));
  key.target.position.copy(centre);
  fill.position.copy(centre).add(new THREE.Vector3(-0.8, 0.4, -0.4).multiplyScalar(dist));
  ground.scale.setScalar(radius * 40);
  ground.position.set(centre.x, reach.min.y - radius * 0.15, centre.z);
  return { home, centre };
}

function load(id) {
  const entry = CATALOG.find((c) => c.id === id) ?? CATALOG[0];
  if (current) { mover.detach(); scene.remove(current.root); current.root.traverse((o) => { o.geometry?.dispose?.(); }); }
  const built = entry.build();
  const { root, parts, assemblies } = built;
  decorate(parts);
  scene.add(root);
  // The camera fits the part assembled and fully apart, so nothing leaves the frame.
  const box = new THREE.Box3().setFromObject(root);
  const size = box.getSize(new THREE.Vector3());
  built.groups.forEach((g, i) => g.position.set(...assemblies[i].offset));
  root.updateMatrixWorld(true);
  const reach = new THREE.Box3().setFromObject(root).union(box);
  built.groups.forEach((g) => g.position.set(0, 0, 0));
  root.updateMatrixWorld(true);
  const { home, centre } = frameOn(reach);
  if (board.active) root.visible = false;
  current = { entry, ...built, size, home, centre };
  springs = assemblies.map(() => ({ x: 0, v: 0, target: 0, at: 0 }));
  apart = false; hover = -1; picked = -1;
  DEFAULT = root.userData.spec ?? "";
  title.textContent = root.name;
  button("explode").setAttribute("aria-pressed", "false");
  button("explode").disabled = assemblies.length < 2;
  buildLegend();
  paintFocus();
  document.querySelectorAll(".catalog button").forEach((b) => b.setAttribute("aria-current", String(b.dataset.id === entry.id)));
  if (location.hash.slice(1) !== entry.id) history.replaceState(null, "", "#" + entry.id);
}

function setApart(next) {
  if (!current || current.assemblies.length < 2) return;
  apart = next;
  const now = performance.now();
  const maxDelay = Math.max(...current.assemblies.map((a) => a.delay ?? 0));
  current.assemblies.forEach((a, i) => { springs[i].target = apart ? 1 : 0; springs[i].at = now + 1000 * (apart ? a.delay ?? 0 : maxDelay - (a.delay ?? 0)); });
  button("explode").setAttribute("aria-pressed", String(apart));
}

const ray = new THREE.Raycaster();
const pointer = new THREE.Vector2();
function partAt(event) {
  const r = canvas.getBoundingClientRect();
  pointer.set(((event.clientX - r.left) / r.width) * 2 - 1, -((event.clientY - r.top) / r.height) * 2 + 1);
  ray.setFromCamera(pointer, camera);
  const hit = ray.intersectObjects(current.parts, true).find((h) => h.object.isMesh);
  let o = hit?.object;
  while (o && o.userData.part === undefined) o = o.parent;
  return o ? o.userData.part : -1;
}
function paintFocus() {
  if (!current) return;
  const on = hover >= 0 ? hover : picked;
  const glow = new THREE.Color(html.dataset.theme === "light" ? 0x335577 : 0x2a4060);
  current.parts.forEach((p, i) => {
    const lit = i === on;
    for (const m of p.userData.meshes) {
      m.material.emissive.copy(lit ? glow : m.userData.base);
      for (const c of m.children) if (c.userData.outline) c.material = lit ? litLine : lineMat;
    }
  });
  readout.textContent = on >= 0 ? `${current.parts[on].userData.name} · ${current.parts[on].userData.spec}` : DEFAULT;
  document.querySelectorAll(".legend li").forEach((li) => li.toggleAttribute("data-on", +li.dataset.part === on));
}
function select(index) {
  picked = index;
  if (picked < 0) mover.detach();
  else if (button("move").getAttribute("aria-pressed") === "true") mover.attach(current.parts[picked]);
  paintFocus();
}

let down = null;
canvas.addEventListener("pointerdown", (e) => { down = [e.clientX, e.clientY]; hold(); });
canvas.addEventListener("pointermove", (e) => { if (e.buttons || !current) return; if (board.active) { board.pointer(e); return; } const h = partAt(e); if (h !== hover) { hover = h; paintFocus(); } });
canvas.addEventListener("pointerleave", () => { hover = -1; paintFocus(); });
canvas.addEventListener("pointerup", (e) => {
  if (!down || Math.hypot(e.clientX - down[0], e.clientY - down[1]) > 4 || mover.dragging) return;
  if (board.active) { board.place(e); return; }
  select(partAt(e));
});

const legend = document.querySelector(".legend");
function buildLegend() {
  legend.innerHTML = current.parts.map((p, i) => `<li data-part="${i}"><b>${String(i + 1).padStart(2, "0")}</b>${p.userData.name}</li>`).join("");
}
legend.addEventListener("click", (e) => { const li = e.target.closest("li"); if (li) { hold(); select(+li.dataset.part); } });
legend.addEventListener("pointerover", (e) => { const li = e.target.closest("li"); if (li) { hover = +li.dataset.part; paintFocus(); } });
legend.addEventListener("pointerleave", () => { hover = -1; paintFocus(); });

// Catalogue list, grouped.
const list = document.querySelector(".catalog");
const cats = [...new Set(CATALOG.map((c) => c.category))];
list.innerHTML = cats.map((cat) => `<h2>${cat}</h2>` + CATALOG.filter((c) => c.category === cat).map((c) => `<button data-id="${c.id}">${c.title ?? c.id}</button>`).join("")).join("");
list.addEventListener("click", (e) => { const b = e.target.closest("button"); if (!b) return; if (board.active) board.choose(b.dataset.id); else load(b.dataset.id); });
addEventListener("hashchange", () => { const id = location.hash.slice(1); if (id && id !== current?.entry.id) load(id); });

function hold() {
  controls.autoRotate = false;
  button("spin").setAttribute("aria-pressed", "false");
}
function view(dir) { hold(); camera.position.copy(current.centre).add(dir.clone().normalize().multiplyScalar(camera.position.distanceTo(controls.target))); controls.target.copy(current.centre); controls.update(); }
function applyTheme() {
  const light = html.dataset.theme === "light";
  lineMat.color.set(light ? 0x1a1a1a : 0x000000);
  lineMat.opacity = light ? 0.45 : 0.6;
  litLine.color.set(light ? 0x000000 : 0xffffff);
  ground.material.opacity = light ? 0.18 : 0.45;
  renderer.setClearColor(light ? 0xfbfbfa : 0x131313, 1);
  paintFocus();
}
document.querySelector(".bar").addEventListener("click", (e) => {
  const act = e.target.closest("button")?.dataset.act;
  if (!act || !current) return;
  if (act === "explode") { hold(); setApart(!apart); }
  if (act === "spin") { controls.autoRotate = !controls.autoRotate; e.target.setAttribute("aria-pressed", String(controls.autoRotate)); }
  if (act === "move") {
    const on = e.target.getAttribute("aria-pressed") !== "true";
    e.target.setAttribute("aria-pressed", String(on));
    if (on && picked >= 0) mover.attach(current.parts[picked]); else mover.detach();
  }
  if (act === "reset") { for (const p of current.parts) p.position.set(0, 0, 0); select(-1); setApart(false); hold(); camera.position.copy(current.home); controls.target.copy(current.centre); }
  if (act === "top") view(new THREE.Vector3(0.001, 1, 0.001));
  if (act === "bottom") view(new THREE.Vector3(0.001, -1, 0.001));
  if (act === "theme") { html.dataset.theme = html.dataset.theme === "light" ? "dark" : "light"; try { localStorage.setItem("parts-theme", html.dataset.theme); } catch {} applyTheme(); }
  if (act === "glb") exportGlb();
  if (act === "board") {
    const on = !board.active;
    e.target.setAttribute("aria-pressed", String(on));
    for (const b of ["explode", "move", "glb"]) button(b).disabled = on || (b === "explode" && current.assemblies.length < 2);
    button("layout").hidden = !on;
    button("demo").hidden = !on;
    button("blinker").hidden = !on;
    button("follow").hidden = !on;
    mover.detach();
    setApart(false);
    current.root.visible = !on;
    if (on) board.open(current.entry.id); else { board.close(); load(current.entry.id); }
  }
  if (act === "layout") board.copyLayout();
  if (act === "demo") board.demo();
  if (act === "blinker") board.loadProject("blinker-555");
  if (act === "follow") {
    if (live) { live.stop(); live = null; e.target.setAttribute("aria-pressed", "false"); e.target.textContent = "Follow Bench Buddy"; return; }
    const url = new URLSearchParams(location.search).get("live") ?? "http://localhost:8766";
    e.target.setAttribute("aria-pressed", "true");
    live = follow(board, { url, onStatus: (s) => { e.target.textContent = s.connected ? `Following · ${s.state || "connected"}` : "Bench Buddy offline (retrying)"; if (s.said) readout.textContent = `Bench Buddy: “${s.said}”`; } });
  }
});
canvas.addEventListener("keydown", (e) => {
  if (!current) return;
  if (e.key === "b" || e.key === "B") { button("board").click(); return; }
  if (board.active) { board.key(e); return; }
  if (e.key === "e" || e.key === "E") { hold(); setApart(!apart); }
  if (e.key === "g" || e.key === "G") button("move").click();
  if (e.key === "Escape") select(-1);
  if (e.key === "ArrowRight" || e.key === "ArrowLeft") {
    e.preventDefault(); hold();
    const n = current.parts.length, step = e.key === "ArrowRight" ? 1 : -1;
    select(((picked < 0 ? (step > 0 ? -1 : 0) : picked) + step + n) % n);
  }
});

function exportGlb() {
  const copy = current.root.clone(true);
  copy.traverse((o) => { if (o.userData.outline) o.removeFromParent(); });
  new GLTFExporter().parse(copy, (glb) => {
    const a = document.createElement("a");
    a.href = URL.createObjectURL(new Blob([glb], { type: "model/gltf-binary" }));
    a.download = `${current.entry.id}.glb`;
    a.click();
  }, (err) => console.error(err), { binary: true });
}

function resize() {
  const w = canvas.clientWidth, h = canvas.clientHeight, pr = renderer.getPixelRatio();
  if (canvas.width !== Math.round(w * pr) || canvas.height !== Math.round(h * pr)) {
    renderer.setSize(w, h, false);
    camera.aspect = w / h;
    camera.updateProjectionMatrix();
  }
}
let last = performance.now();
function frame(now) {
  const dt = Math.min((now - last) / 1000, 1 / 30);
  last = now;
  resize();
  if (current) springs.forEach((s, i) => {
    const want = now >= s.at ? s.target : 1 - s.target;
    if (still.matches) { s.x = want; s.v = 0; }
    else for (let k = 0; k < 4; k++) { s.v += ((want - s.x) * 110 - s.v * 19) * dt / 4; s.x += s.v * dt / 4; }
    const [ox, oy, oz] = current.assemblies[i].offset;
    current.groups[i].position.set(ox * s.x, oy * s.x, oz * s.x);
  });
  board.tick?.(dt);
  controls.update();
  renderer.render(scene, camera);
  requestAnimationFrame(frame);
}
let live = null;
const board = createBoard({ THREE, scene, camera, controls, canvas, CATALOG, decorate, frame: frameOn, readout, legend, hold, lineMat });
applyTheme();
load(location.hash.slice(1) || CATALOG[0].id);
if (new URLSearchParams(location.search).has("live")) { button("board").click(); button("follow").click(); }
requestAnimationFrame(frame);
window.__viewer = { THREE, scene, camera, controls, load, setApart, select, view, get current() { return current; }, exportGlb, CATALOG, board };
