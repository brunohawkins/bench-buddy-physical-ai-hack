// Shared builder for component models. Units are millimetres. Component coordinates: x right,
// y back (away from the viewer), z up; the kit maps them to three.js (y up).
// A model is { root, groups, parts, assemblies }: parts are named groups that highlight and report
// as one; assemblies are groups that move apart together (offsets in three.js axes).
import * as THREE from "three";
import { RoundedBoxGeometry } from "three/addons/geometries/RoundedBoxGeometry.js";
import { mergeGeometries } from "three/addons/utils/BufferGeometryUtils.js";

export const at = (x, y, z) => new THREE.Vector3(x, z, -y);

const PALETTE = {
  pcbGreen: { color: 0x1f6e43, roughness: 0.75 },
  pcbBlue: { color: 0x1d4f9a, roughness: 0.7 },
  pcbBlack: { color: 0x1c1f1d, roughness: 0.7 },
  pcbRed: { color: 0xa8232c, roughness: 0.7 },
  gold: { color: 0xd4aa4f, roughness: 0.35, metalness: 0.85 },
  tin: { color: 0xc9cdd1, roughness: 0.4, metalness: 0.8 },
  copper: { color: 0xc07a45, roughness: 0.35, metalness: 0.85 },
  steel: { color: 0xc4c7cb, roughness: 0.32, metalness: 0.9 },
  aluminium: { color: 0x9da3a8, roughness: 0.45, metalness: 0.8 },
  shell: { color: 0xb8bcc1, roughness: 0.38, metalness: 0.85 },
  black: { color: 0x1b1b1d, roughness: 0.55 },
  chip: { color: 0x141416, roughness: 0.45, metalness: 0.05 },
  hole: { color: 0x050505, roughness: 0.9 },
  white: { color: 0xf1f0ec, roughness: 0.6 },
  board: { color: 0xf3f1ea, roughness: 0.75 },
  jst: { color: 0xeeeae2, roughness: 0.6 },
  latch: { color: 0xd9d0b8, roughness: 0.6 },
  blue: { color: 0x2f5bd8, roughness: 0.5 },
  red: { color: 0xd63a3a, roughness: 0.5 },
  ceramic: { color: 0xd9a54a, roughness: 0.6 },
  resistorBody: { color: 0xd9c49a, roughness: 0.6 },
  sleeveBlue: { color: 0x1f3f8a, roughness: 0.45 },
  sleeveStripe: { color: 0xc8d0e0, roughness: 0.5 },
  rubber: { color: 0x2a2a2a, roughness: 0.9 },
  glassOrange: { color: 0xe08a3a, roughness: 0.1, transparent: true, opacity: 0.7 },
  epoxyRed: { color: 0xff3b3b, roughness: 0.15, transparent: true, opacity: 0.55, emissive: 0x3a0000 },
  lens: { color: 0x1a2236, roughness: 0.05, metalness: 0.6 },
  ledGreen: { color: 0x3ccf72, roughness: 0.3, emissive: 0x1a6a38 },
  ledRed: { color: 0xff4d4d, roughness: 0.3, emissive: 0x7a1a1a },
  ledAmber: { color: 0xf0a020, roughness: 0.3, emissive: 0x6a4a10 },
  die: { color: 0x2a3150, roughness: 0.25, metalness: 0.4 },
  substrate: { color: 0x3b4a32, roughness: 0.6 },
  foam: { color: 0xe9e4d6, roughness: 0.95 },
  // Resistor colour code
  band0: { color: 0x111111, roughness: 0.6 }, band1: { color: 0x6b3a1e, roughness: 0.6 }, band2: { color: 0xc62828, roughness: 0.6 },
  band3: { color: 0xef6c00, roughness: 0.6 }, band4: { color: 0xf9d71c, roughness: 0.6 }, band5: { color: 0x2e7d32, roughness: 0.6 },
  band6: { color: 0x1565c0, roughness: 0.6 }, band7: { color: 0x7b1fa2, roughness: 0.6 }, band8: { color: 0x8a8a8a, roughness: 0.6 },
  band9: { color: 0xf5f5f5, roughness: 0.6 }, bandGold: { color: 0xc9a43c, roughness: 0.35, metalness: 0.8 }, bandSilver: { color: 0xbfc3c7, roughness: 0.35, metalness: 0.8 },
  // Wire insulation
  wireRed: { color: 0xd32f2f, roughness: 0.55 }, wireBlack: { color: 0x222222, roughness: 0.55 }, wireYellow: { color: 0xf2c230, roughness: 0.55 },
  wireGreen: { color: 0x2e9e4f, roughness: 0.55 }, wireBlue: { color: 0x2f6fd6, roughness: 0.55 }, wireOrange: { color: 0xef7d22, roughness: 0.55 },
};

export function model(name, assemblies = [{ name, offset: [0, 0, 0], delay: 0 }], { labels = typeof document !== "undefined" } = {}) {
  const cache = {};
  const mat = (key) => {
    if (typeof key !== "string") return key;
    if (!cache[key]) {
      const spec = PALETTE[key];
      if (!spec) throw new Error(`unknown material ${key}`);
      cache[key] = new THREE.MeshStandardMaterial({ metalness: 0, ...spec });
      cache[key].name = key;
    }
    return cache[key];
  };
  const root = new THREE.Group();
  root.name = name;
  const groups = assemblies.map((a) => {
    const g = new THREE.Group();
    g.name = a.name;
    g.userData.offset = a.offset;
    root.add(g);
    return g;
  });
  const parts = [];

  const k = {
    root, groups, parts, assemblies, mat,
    part(assembly, partName, spec) {
      const g = new THREE.Group();
      g.name = partName;
      g.userData = { part: parts.length, name: partName, spec, assembly };
      groups[assembly].add(g);
      parts.push(g);
      return g;
    },
    mesh(target, geometry, m, meshName) {
      const out = new THREE.Mesh(geometry, mat(m));
      if (meshName) out.name = meshName;
      target.add(out);
      return out;
    },
    // Axis-aligned box from ranges, optionally rounded.
    box(target, x0, x1, y0, y1, z0, z1, m, r = 0) {
      const w = x1 - x0, h = z1 - z0, d = y1 - y0;
      const radius = Math.min(r, Math.min(w, h, d) / 2 - 0.01);
      const geometry = radius > 0.02 ? new RoundedBoxGeometry(w, h, d, 2, radius) : new THREE.BoxGeometry(w, h, d);
      const out = k.mesh(target, geometry, m);
      out.position.copy(at((x0 + x1) / 2, (y0 + y1) / 2, (z0 + z1) / 2));
      return out;
    },
    // Many small boxes merged into one mesh.
    boxes(target, list, m) {
      if (!list.length) return null;
      const geos = list.map(([x0, x1, y0, y1, z0, z1]) => {
        const g = new THREE.BoxGeometry(x1 - x0, z1 - z0, y1 - y0);
        const c = at((x0 + x1) / 2, (y0 + y1) / 2, (z0 + z1) / 2);
        g.translate(c.x, c.y, c.z);
        return g;
      });
      return k.mesh(target, mergeGeometries(geos), m);
    },
    // A cylinder (or cone, with r1) between two points.
    rod(target, a, b, r, m, { r1 = r, segments = 24 } = {}) {
      const pa = at(...a), pb = at(...b);
      const len = pa.distanceTo(pb);
      const out = k.mesh(target, new THREE.CylinderGeometry(r1, r, len, segments), m);
      out.position.copy(pa).add(pb).multiplyScalar(0.5);
      out.quaternion.setFromUnitVectors(new THREE.Vector3(0, 1, 0), pb.clone().sub(pa).normalize());
      return out;
    },
    // A turned part: profile is [[radius, s], …] along the axis from a to b's direction, s in mm from a.
    lathe(target, profile, a, dir, m, segments = 40) {
      const geometry = new THREE.LatheGeometry(profile.map(([r, s]) => new THREE.Vector2(Math.max(r, 0.0001), s)), segments);
      const out = k.mesh(target, geometry, m);
      out.position.copy(at(...a));
      out.quaternion.setFromUnitVectors(new THREE.Vector3(0, 1, 0), at(...dir).normalize());
      return out;
    },
    // A swept tube through 3D points (component axes).
    tube(target, points, r, m, { segments = 64, radial = 12, tension = 0.5 } = {}) {
      const curve = new THREE.CatmullRomCurve3(points.map((p) => at(...p)), false, "catmullrom", tension);
      return k.mesh(target, new THREE.TubeGeometry(curve, segments, r, radial, false), m);
    },
    sphere(target, c, r, m) {
      const out = k.mesh(target, new THREE.SphereGeometry(r, 24, 16), m);
      out.position.copy(at(...c));
      return out;
    },
    // A flat ring lying on a horizontal face.
    ring(target, x, y, z, r0, r1, m, down = false) {
      const out = k.mesh(target, new THREE.RingGeometry(r0, r1, 40), m);
      out.rotation.x = down ? Math.PI / 2 : -Math.PI / 2;
      out.position.copy(at(x, y, z));
      return out;
    },
    // A rounded-rectangle plate with round holes, extruded up from z0.
    plate(target, w, d, z0, h, m, { r = 1, holes = [], x0 = 0, y0 = 0 } = {}) {
      const s = new THREE.Shape();
      s.moveTo(r, 0);
      s.lineTo(w - r, 0); s.absarc(w - r, r, r, -Math.PI / 2, 0);
      s.lineTo(w, d - r); s.absarc(w - r, d - r, r, 0, Math.PI / 2);
      s.lineTo(r, d); s.absarc(r, d - r, r, Math.PI / 2, Math.PI);
      s.lineTo(0, r); s.absarc(r, r, r, Math.PI, Math.PI * 1.5);
      for (const [x, y, hr] of holes) {
        const p = new THREE.Path();
        p.absarc(x - x0, y - y0, hr, 0, Math.PI * 2, true);
        s.holes.push(p);
      }
      const geometry = new THREE.ExtrudeGeometry(s, { depth: h, bevelEnabled: false, curveSegments: 20 });
      geometry.rotateX(-Math.PI / 2);
      geometry.translate(x0, z0, -y0);
      return k.mesh(target, geometry, m);
    },
    // Through-hole pins in a 2.54 mm grid: tops at z1, bottoms at z0.
    pins(target, cols, rows, cx, cy, z0, z1, m = "gold", { pitch = 2.54, size = 0.64 } = {}) {
      const list = [];
      const x0 = cx - ((cols - 1) * pitch) / 2, y0 = cy - ((rows - 1) * pitch) / 2;
      for (let i = 0; i < cols; i++) for (let j = 0; j < rows; j++) {
        const x = x0 + i * pitch, y = y0 + j * pitch;
        list.push([x - size / 2, x + size / 2, y - size / 2, y + size / 2, z0, z1]);
      }
      return k.boxes(target, list, m);
    },
    // Printed text on a horizontal face (browser only: canvas texture). up = "y" reads with +y up.
    label(target, x, y, z, w, h, lines, { color = "#d8d8d8", weight = 600, family = "ui-monospace, Menlo, Consolas, monospace", rotate = 0, face = "top" } = {}) {
      if (!labels) return;
      const canvas = document.createElement("canvas");
      canvas.width = 1024;
      canvas.height = Math.max(16, Math.round((1024 * h) / w));
      const ctx = canvas.getContext("2d");
      ctx.fillStyle = color;
      ctx.textAlign = "center";
      ctx.textBaseline = "middle";
      lines.forEach((line, i) => {
        const [text, scale = 1] = Array.isArray(line) ? line : [line];
        let px = (canvas.height / lines.length) * 0.78 * scale;
        ctx.font = `${weight} ${px}px ${family}`;
        const wide = ctx.measureText(text).width;
        if (wide > canvas.width * 0.96) { px *= (canvas.width * 0.96) / wide; ctx.font = `${weight} ${px}px ${family}`; }
        ctx.fillText(text, canvas.width / 2, (canvas.height * (i + 0.5)) / lines.length);
      });
      const tex = new THREE.CanvasTexture(canvas);
      tex.anisotropy = 8;
      tex.colorSpace = THREE.SRGBColorSpace;
      const out = new THREE.Mesh(new THREE.PlaneGeometry(w, h), new THREE.MeshBasicMaterial({ map: tex, transparent: true, depthWrite: false }));
      if (face === "top") { out.rotation.x = -Math.PI / 2; out.rotation.z = rotate; out.position.copy(at(x, y, z + 0.02)); }
      if (face === "front") { out.position.copy(at(x, y - 0.02, z)); }
      if (face === "back") { out.rotation.y = Math.PI; out.position.copy(at(x, y + 0.02, z)); }
      out.userData.label = true;
      target.add(out);
    },
    done(meta = {}) {
      root.userData = { ...root.userData, ...meta, assemblies, units: "millimetres" };
      return { root, groups, parts, assemblies };
    },
  };
  return k;
}

// Resistor colour bands for a value in ohms: [digit, digit, multiplier] material keys.
export function bandsOf(ohms) {
  const exp = Math.floor(Math.log10(ohms)) - 1;
  const digits = Math.round(ohms / 10 ** exp);
  const d = String(digits).padStart(2, "0");
  const mult = exp < 0 ? (exp === -1 ? "bandGold" : "bandSilver") : `band${exp}`;
  return [`band${d[0]}`, `band${d[1]}`, mult];
}

export function ohmsText(ohms) {
  if (ohms >= 1e6) return `${+(ohms / 1e6).toPrecision(3)} MΩ`;
  if (ohms >= 1e3) return `${+(ohms / 1e3).toPrecision(3)} kΩ`;
  return `${ohms} Ω`;
}
