// node export-glb.mjs → raspberry-pi-5-4gb.glb (no printed labels: those need a browser canvas;
// the viewer's "Download .glb" button exports the same model with labels).
import { writeFileSync } from "node:fs";
import { GLTFExporter } from "three/addons/exporters/GLTFExporter.js";
import { buildPi5, ASSEMBLIES } from "./model.js";

globalThis.FileReader ??= class {
  readAsArrayBuffer(blob) { blob.arrayBuffer().then((buffer) => { this.result = buffer; this.onloadend?.(); this.onload?.(); }); }
  readAsDataURL(blob) { blob.arrayBuffer().then((buffer) => { this.result = `data:${blob.type};base64,` + Buffer.from(buffer).toString("base64"); this.onloadend?.(); this.onload?.(); }); }
};

const { root, parts } = buildPi5({ labels: false });
// Keep part names, specs and explode offsets in the file so any app can read them (glTF "extras").
root.userData = { assemblies: ASSEMBLIES, units: "millimetres", source: "Raspberry Pi 5 mechanical drawing" };
const glb = await new GLTFExporter().parseAsync(root, { binary: true });
writeFileSync("raspberry-pi-5-4gb.glb", Buffer.from(glb));
console.log("wrote raspberry-pi-5-4gb.glb", (glb.byteLength / 1024).toFixed(0), "KB ·", parts.length, "parts");
