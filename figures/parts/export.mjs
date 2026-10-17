// node parts/export.mjs → parts/glb/<id>.glb for every catalogue entry, plus parts/glb/manifest.json.
// Printed labels need a browser canvas, so Node exports leave them out; the gallery's
// "Download .glb" button exports the same model with its labels.
import { mkdirSync, writeFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import * as THREE from "three";
import { GLTFExporter } from "three/addons/exporters/GLTFExporter.js";
import { CATALOG } from "./catalog.js";

globalThis.FileReader ??= class {
  readAsArrayBuffer(blob) { blob.arrayBuffer().then((b) => { this.result = b; this.onloadend?.(); this.onload?.(); }); }
  readAsDataURL(blob) { blob.arrayBuffer().then((b) => { this.result = `data:${blob.type};base64,` + Buffer.from(b).toString("base64"); this.onloadend?.(); this.onload?.(); }); }
};
const warn = console.warn;
console.warn = (msg, ...rest) => { if (!String(msg).includes("normalized normal")) warn(msg, ...rest); };

const OUT = join(dirname(fileURLToPath(import.meta.url)), "glb");
mkdirSync(OUT, { recursive: true });
const manifest = [];
for (const entry of CATALOG) {
  const m = entry.build();
  const size = new THREE.Box3().setFromObject(m.root).getSize(new THREE.Vector3());
  const glb = await new GLTFExporter().parseAsync(m.root, { binary: true });
  writeFileSync(join(OUT, `${entry.id}.glb`), Buffer.from(glb));
  manifest.push({
    id: entry.id,
    title: entry.title,
    name: m.root.name,
    category: entry.category,
    demo: !!entry.demo,
    spec: m.root.userData.spec ?? "",
    file: `${entry.id}.glb`,
    sizeMm: size.toArray().map((v) => +v.toFixed(1)),
    assemblies: m.assemblies.map((a) => a.name),
    parts: m.parts.map((p) => ({ name: p.userData.name, spec: p.userData.spec, assembly: p.userData.assembly })),
    // Where each leg ends (component axes, mm) and how deep it sits in a breadboard; the
    // breadboard itself lists every hole by name.
    pins: m.root.userData.pins,
    legTip: m.root.userData.tip,
    insertDepth: m.root.userData.insert,
    leadSpans: m.root.userData.spans,
    holes: m.root.userData.holes,
  });
  console.log(entry.id.padEnd(26), `${(glb.byteLength / 1024).toFixed(0).padStart(5)} KB`, m.parts.length, "parts");
}
writeFileSync(join(OUT, "manifest.json"), JSON.stringify({ units: "millimetres, three.js axes (y up)", models: manifest }, null, 2));
console.log("wrote", manifest.length, "models + manifest.json");
