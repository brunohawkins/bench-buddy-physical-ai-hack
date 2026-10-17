// node build-page.mjs → index.html: viewer.src.html with model.js inlined, so the page works
// when opened straight from disk (file://), where browsers block importing a local module.
import { readFileSync, writeFileSync } from "node:fs";

const model = readFileSync("model.js", "utf8");
const imports = model.match(/^import .*$/gm).filter((line) => !line.includes('from "three";'));
const body = model.replace(/^import .*$/gm, "").replace(/^export /gm, "");
const page = readFileSync("viewer.src.html", "utf8").replace(
  'import { buildPi5, ASSEMBLIES } from "./model.js";',
  `${imports.join("\n")}\n// ── model.js (inlined by build-page.mjs) ──\n${body}\n// ── viewer ──`,
);
if (page.includes('from "./model.js"')) throw new Error("model import not found in viewer.src.html");
writeFileSync("index.html", page);
console.log("wrote index.html");
