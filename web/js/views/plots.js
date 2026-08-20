/** 캔버스 렌더러 (DOM 전용 — 수치는 lib/plot.js·lib/replay.js) — 히트맵·산점도·시계열·궤적. */

import { el } from "../dom.js";
import { linScale, niceTicks } from "../lib/plot.js";
import { extent } from "../lib/replay.js";

const FONT = "11px -apple-system, 'Segoe UI', sans-serif";

export function makeCanvas(width, height) {
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
 * 애플 스타일: 라운드 셀(3px 갭), 세미볼드 타이틀·셀 텍스트, 라이트 그레이 축 라벨.
 */
export function heatmapCanvas(pivot, cellOf, { title = "", width = 560 } = {}) {
  const { machs, alts } = pivot;
  const mL = 64, mT = 28, mR = 10, mB = 34;
  const cw = Math.min(90, (width - mL - mR) / Math.max(1, machs.length));
  const ch = 34;
  const height = mT + ch * alts.length + mB;
  const { canvas, ctx } = makeCanvas(width, height);

  const cellRect = (x, y, w, h) => {
    ctx.beginPath();
    if (ctx.roundRect) ctx.roundRect(x, y, w, h, 6);
    else ctx.rect(x, y, w, h);
    ctx.fill();
  };

  ctx.font = "600 12px -apple-system, 'Segoe UI', sans-serif";
  ctx.fillStyle = "#1d1d1f";
  ctx.fillText(title, mL, 16);
  ctx.font = FONT;
  alts.forEach((alt, j) => {
    const y = mT + (alts.length - 1 - j) * ch; // 고도는 위로 증가
    machs.forEach((mach, i) => {
      const x = mL + i * cw;
      const entry = pivot.at(mach, alt);
      const cell = entry ? cellOf(entry) : null;
      ctx.fillStyle = cell ? cell.color : "#f2f2f7";
      cellRect(x, y, cw - 3, ch - 3);
      if (cell && cell.text != null) {
        ctx.font = "600 11px -apple-system, 'Segoe UI', sans-serif";
        ctx.fillStyle = "#ffffff";
        ctx.fillText(String(cell.text), x + 7, y + ch / 2 + 3);
        ctx.font = FONT;
      }
    });
    ctx.fillStyle = "#86868b";
    ctx.fillText(`${alt} m`, 6, y + ch / 2 + 3);
  });
  machs.forEach((mach, i) => {
    ctx.fillStyle = "#86868b";
    ctx.fillText(`M${mach}`, mL + i * cw + 7, mT + ch * alts.length + 16);
  });
  return canvas;
}

const MODE_BAND_COLORS = ["#e8f1fe", "#e6f6ea", "#fdf6df", "#fdeaea", "#efe9fb", "#e7f6f6"];

/** 선 차트 — series: [{label, data, color}], bands: modeSpans 결과 (배경 밴드).
 * x축은 t 배열 (기본 시각 [s] — xUnit으로 변경 가능, 예: V-n 선도의 "m/s").
 * markers=true면 각 데이터점에 원 마커 — 격자점(브레이크포인트)이 유의미한
 * 테이블 플롯용 (선 = 구간 선형 보간임을 드러냄).
 * 시리즈별 옵션(오버레이용): x = 개별 x 배열(t와 다른 표본점 — 범위는 t 안,
 * 축 스케일은 t 기준 유지), dash = 점선 패턴, markers: false = 마커 제외,
 * label "" = 범례 생략. */
export function lineChartCanvas(t, series, { title = "", width = 620, height = 190, bands = [], xUnit = "s", markers = false } = {}) {
  const { canvas, ctx } = makeCanvas(width, height);
  const mL = 56, mT = 22, mR = 10, mB = 24;
  const t0 = t[0] ?? 0;
  const t1 = t[t.length - 1] ?? 1;
  let lo = Infinity;
  let hi = -Infinity;
  for (const s of series) {
    const [a, b] = extent(s.data);
    lo = Math.min(lo, a);
    hi = Math.max(hi, b);
  }
  if (!(lo < hi)) { lo -= 1; hi += 1; }
  const pad = 0.06 * (hi - lo);
  const px = linScale(t0, t1, mL, width - mR);
  const py = linScale(lo - pad, hi + pad, height - mB, mT);

  bands.forEach((b, k) => {
    const xa = px(t[b.i0]);
    const xb = px(t[Math.min(b.i1, t.length - 1)]);
    ctx.fillStyle = MODE_BAND_COLORS[k % MODE_BAND_COLORS.length];
    ctx.fillRect(xa, mT, xb - xa, height - mT - mB);
    ctx.fillStyle = "#86868b";
    if (b.mode) ctx.fillText(b.mode, xa + 3, mT + 11);
  });
  ctx.strokeStyle = "#e5e5ea";
  ctx.beginPath();
  for (const tk of niceTicks(lo, hi, 4)) {
    ctx.moveTo(mL, py(tk));
    ctx.lineTo(width - mR, py(tk));
    ctx.fillStyle = "#86868b";
    ctx.fillText(fmtTick(tk), 4, py(tk) + 3);
  }
  for (const tk of niceTicks(t0, t1, 7)) {
    ctx.fillStyle = "#86868b";
    ctx.fillText(`${fmtTick(tk)}${xUnit}`, px(tk) - 8, height - 8);
  }
  ctx.stroke();
  series.forEach((s, si) => {
    const xs = s.x ?? t;
    ctx.strokeStyle = s.color;
    ctx.lineWidth = s.dash ? 1.2 : 1.4;
    if (s.dash) ctx.setLineDash(s.dash);
    ctx.beginPath();
    let started = false;
    s.data.forEach((v, i) => {
      if (typeof v !== "number") { started = false; return; } // null(NaN) 구간 끊기
      if (!started) { ctx.moveTo(px(xs[i]), py(v)); started = true; }
      else ctx.lineTo(px(xs[i]), py(v));
    });
    ctx.stroke();
    ctx.setLineDash([]);
    if (markers && s.markers !== false) {
      ctx.fillStyle = s.color;
      s.data.forEach((v, i) => {
        if (typeof v !== "number") return;
        ctx.beginPath();
        ctx.arc(px(xs[i]), py(v), 2.6, 0, 2 * Math.PI);
        ctx.fill();
      });
    }
    if (s.label) {
      ctx.fillStyle = s.color;
      ctx.fillText(s.label, mL + 70 * si, 14);
    }
  });
  ctx.fillStyle = "#1d1d1f";
  ctx.fillText(title, width - mR - 7 * title.length, 14);
  return canvas;
}

function fmtTick(v) {
  return Math.abs(v) >= 1000 ? String(Math.round(v)) : String(Math.round(v * 1000) / 1000);
}

/** 지상 궤적 (NED 평면, 북쪽 위) — 웨이포인트 원(도달 반경)·시각 마커. */
export function trackCanvas(pn, pe, waypoints, acceptRadius, { markerIdx = null, width = 380, height = 380 } = {}) {
  const { canvas, ctx } = makeCanvas(width, height);
  const m = 42;
  const wpN = waypoints.map((w) => w[0]);
  const wpE = waypoints.map((w) => w[1]);
  const [n0, n1] = extent([...pn, ...wpN]);
  const [e0, e1] = extent([...pe, ...wpE]);
  // 등축 스케일 — 왜곡 없는 기하 (선회반경 판단용)
  const span = Math.max(n1 - n0, e1 - e0, 1) * 1.15;
  const cN = (n0 + n1) / 2;
  const cE = (e0 + e1) / 2;
  const px = linScale(cE - span / 2, cE + span / 2, m, width - m);
  const py = linScale(cN - span / 2, cN + span / 2, height - m, m);
  const kScale = (width - 2 * m) / span; // m → px

  ctx.strokeStyle = "#e5e5ea";
  ctx.beginPath();
  for (const tk of niceTicks(cE - span / 2, cE + span / 2, 5)) {
    ctx.moveTo(px(tk), m);
    ctx.lineTo(px(tk), height - m);
    ctx.fillStyle = "#86868b";
    ctx.fillText(`${Math.round(tk)}`, px(tk) - 10, height - m + 14);
  }
  for (const tk of niceTicks(cN - span / 2, cN + span / 2, 5)) {
    ctx.moveTo(m, py(tk));
    ctx.lineTo(width - m, py(tk));
    ctx.fillStyle = "#86868b";
    ctx.fillText(`${Math.round(tk)}`, 2, py(tk) + 3);
  }
  ctx.stroke();
  ctx.fillStyle = "#86868b";
  ctx.fillText("E [m] →  (북쪽 위)", width / 2 - 40, height - 6);

  for (const [n, e] of waypoints) {
    ctx.strokeStyle = "#ff9500";
    ctx.beginPath();
    ctx.arc(px(e), py(n), Math.max(3, acceptRadius * kScale), 0, 2 * Math.PI);
    ctx.stroke();
    ctx.fillStyle = "#ff9500";
    ctx.beginPath();
    ctx.arc(px(e), py(n), 3, 0, 2 * Math.PI);
    ctx.fill();
  }
  ctx.strokeStyle = "#007aff";
  ctx.lineWidth = 1.6;
  ctx.beginPath();
  let started = false;
  pn.forEach((n, i) => {
    const e = pe[i];
    if (typeof n !== "number" || typeof e !== "number") { started = false; return; }
    if (!started) { ctx.moveTo(px(e), py(n)); started = true; }
    else ctx.lineTo(px(e), py(n));
  });
  ctx.stroke();
  ctx.fillStyle = "#34c759";
  ctx.beginPath();
  ctx.arc(px(pe[0]), py(pn[0]), 4, 0, 2 * Math.PI); // 시작점
  ctx.fill();
  if (markerIdx != null && markerIdx < pn.length) {
    ctx.fillStyle = "#ff3b30";
    ctx.beginPath();
    ctx.arc(px(pe[markerIdx]), py(pn[markerIdx]), 5, 0, 2 * Math.PI);
    ctx.fill();
  }
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

  ctx.fillStyle = "#1d1d1f";
  ctx.fillText(title, mL, 15);
  ctx.strokeStyle = "#e5e5ea";
  ctx.beginPath();
  for (const t of niceTicks(x0, x1, 6)) {
    ctx.moveTo(sx(t), mT);
    ctx.lineTo(sx(t), height - mB);
    ctx.fillStyle = "#86868b";
    ctx.fillText(String(t), sx(t) - 8, height - mB + 14);
  }
  for (const t of niceTicks(y0, y1, 5)) {
    ctx.moveTo(mL, sy(t));
    ctx.lineTo(width - mR, sy(t));
    ctx.fillStyle = "#86868b";
    ctx.fillText(String(t), 4, sy(t) + 3);
  }
  ctx.stroke();
  // 허수축(Re=0) — 안정 경계 강조
  ctx.strokeStyle = "#86868b";
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
