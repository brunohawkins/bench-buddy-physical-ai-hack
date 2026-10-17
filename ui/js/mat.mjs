// Ruler numbers and angle guides printed on the cutting mat. The grid itself is CSS (styles.css .mat).
export function drawMat(svg, cell = 28) {
  const draw = () => {
    const w = innerWidth, h = innerHeight;
    if (w < cell * 2 || h < cell * 2) return;
    svg.setAttribute("viewBox", `0 0 ${w} ${h}`);
    const out = [];
    for (let i = 1; i * cell < w; i++) {
      const x = i * cell;
      const major = i % 5 === 0;
      out.push(`<line class="tick" x1="${x}" y1="0" x2="${x}" y2="${major ? 9 : 5}"/>`);
      out.push(`<text x="${x + 3}" y="${major ? 19 : 15}" class="${major ? "big" : "minor"}">${i}</text>`);
    }
    for (let j = 1; j * cell < h; j++) {
      const y = j * cell;
      const major = j % 5 === 0;
      out.push(`<line class="tick" x1="${w}" y1="${y}" x2="${w - (major ? 9 : 5)}" y2="${y}"/>`);
      out.push(`<text x="${w - 12}" y="${y - 3}" text-anchor="end" class="${major ? "big" : "minor"}">${j}</text>`);
    }
    // 45° and 60° guides out of the bottom-left corner, and a protractor arc
    const ox = 0, oy = h, r = Math.max(w, h) * 1.4;
    for (const deg of [30, 45, 60]) {
      const a = (deg * Math.PI) / 180;
      out.push(`<line x1="${ox}" y1="${oy}" x2="${ox + Math.cos(a) * r}" y2="${oy - Math.sin(a) * r}"/>`);
      out.push(`<text class="deg" x="${ox + Math.cos(a) * 240 + 6}" y="${oy - Math.sin(a) * 240}">${deg}°</text>`);
    }
    out.push(`<path d="M ${ox + 210} ${oy} A 210 210 0 0 0 ${ox} ${oy - 210}"/>`);
    out.push(`<rect x="${cell / 2}" y="${cell / 2}" width="${w - cell}" height="${h - cell}" rx="10" fill="none" stroke="rgba(214,240,224,.16)"/>`);
    svg.innerHTML = out.join("");
  };
  draw();
  addEventListener("resize", draw);
}
