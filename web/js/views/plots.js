/** 캔버스 렌더러 (DOM 전용 — 수치는 lib/plot.js) — 마진 맵 히트맵, 고유치 산점도. */

import { el } from "../dom.js";
import { linScale, niceTicks } from "../lib/plot.js";

const FONT = "11px -apple-system, 'Segoe UI', sans-serif";

function makeCanvas(width, height) {
  const dpr = window.devicePixelRatio || 1;
  const canvas = el("canvas", { class: "plot", width: width * dpr, height: height * dpr });
  canvas.style.width = `${width}px`;
  canvas.style.height = `${height}px`;
  const ctx = canvas.getContext("2d");
  ctx.scale(dpr, dpr);
  ctx.font = FONT;
  return { canvas, ctx };
}

/**
 * (mach×alt) 격자 히트맵 — cellOf(entry)가 {color, text} 반환, null 셀은 빗금 없이 회색.
 */
export function heatmapCanvas(pivot, cellOf, { title = "", width = 560 } = {}) {
  const { machs, alts } = pivot;
  const mL = 64, mT = 28, mR = 10, mB = 34;
  const cw = Math.min(90, (width - mL - mR) / Math.max(1, machs.length));
  const ch = 34;
  const height = mT + ch * alts.length + mB;
  const { canvas, ctx } = makeCanvas(width, height);

  ctx.fillStyle = "#1c2430";
  ctx.fillText(title, mL, 16);
  alts.forEach((alt, j) => {
    const y = mT + (alts.length - 1 - j) * ch; // 고도는 위로 증가
    machs.forEach((mach, i) => {
      const x = mL + i * cw;
      const entry = pivot.at(mach, alt);
      const cell = entry ? cellOf(entry) : null;
      ctx.fillStyle = cell ? cell.color : "#eceef1";
      ctx.fillRect(x, y, cw - 2, ch - 2);
      if (cell && cell.text != null) {
        ctx.fillStyle = "#ffffff";
        ctx.fillText(String(cell.text), x + 6, y + ch / 2 + 3);
      }
    });
    ctx.fillStyle = "#66707e";
    ctx.fillText(`${alt} m`, 6, y + ch / 2 + 3);
  });
  machs.forEach((mach, i) => {
    ctx.fillStyle = "#66707e";
    ctx.fillText(`M${mach}`, mL + i * cw + 6, mT + ch * alts.length + 16);
  });
  return canvas;
}

/** 복소평면 산점도 — points: [{x, y, color, label?}]. 축 십자선 + 눈금. */
export function scatterCanvas(points, { title = "", width = 420, height = 300 } = {}) {
  const { canvas, ctx } = makeCanvas(width, height);
  const mL = 46, mT = 26, mR = 12, mB = 30;
  const xs = points.map((p) => p.x);
  const ys = points.map((p) => p.y);
  const pad = (a, b) => (a === b ? [a - 1, b + 1] : [a - 0.1 * (b - a), b + 0.1 * (b - a)]);
  const [x0, x1] = pad(Math.min(0, ...xs), Math.max(0.1, ...xs));
  const [y0, y1] = pad(Math.min(-0.1, ...ys), Math.max(0.1, ...ys));
  const sx = linScale(x0, x1, mL, width - mR);
  const sy = linScale(y0, y1, height - mB, mT);

  ctx.fillStyle = "#1c2430";
  ctx.fillText(title, mL, 15);
  ctx.strokeStyle = "#d8dce2";
  ctx.beginPath();
  for (const t of niceTicks(x0, x1, 6)) {
    ctx.moveTo(sx(t), mT);
    ctx.lineTo(sx(t), height - mB);
    ctx.fillStyle = "#66707e";
    ctx.fillText(String(t), sx(t) - 8, height - mB + 14);
  }
  for (const t of niceTicks(y0, y1, 5)) {
    ctx.moveTo(mL, sy(t));
    ctx.lineTo(width - mR, sy(t));
    ctx.fillStyle = "#66707e";
    ctx.fillText(String(t), 4, sy(t) + 3);
  }
  ctx.stroke();
  // 허수축(Re=0) — 안정 경계 강조
  ctx.strokeStyle = "#66707e";
  ctx.beginPath();
  ctx.moveTo(sx(0), mT);
  ctx.lineTo(sx(0), height - mB);
  ctx.stroke();
  for (const p of points) {
    ctx.fillStyle = p.color;
    ctx.beginPath();
    ctx.arc(sx(p.x), sy(p.y), 3.5, 0, 2 * Math.PI);
    ctx.fill();
  }
  return canvas;
}
