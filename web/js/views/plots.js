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

/** 연직 단면 궤적 (수평좌표 → 고도) — 3면도의 측면도·정면도.

수평면(trackCanvas)과 달리 **비등축**: 수평 이동이 고도 변화보다 통상 한 자릿수
이상 커서 등축이면 궤적이 직선으로 뭉개진다 (lib/plot.js planeViews). 두 축의
축척이 다르므로 경사각을 눈으로 재면 안 된다 — 캡션에 명시한다.
wpXs: 웨이포인트의 가로축 성분. 웨이포인트에는 고도가 없으므로(고도는 모드
테이블 소관) 점이 아니라 세로 안내선으로만 그린다 — 없는 정보를 그리지 않기 위해.
*/
export function profileCanvas(xs, ys, {
  xLabel = "", yLabel = "", wpXs = [], markerIdx = null,
  width = 380, height = 185,
} = {}) {
  const { canvas, ctx } = makeCanvas(width, height);
  // mT는 세로축 라벨 한 줄 몫만 — 평면 이름은 축 라벨로 충분해 제목을 그리지 않는다
  const mL = 52, mT = 18, mR = 12, mB = 28;
  const [x0r, x1r] = extent([...xs, ...wpXs]);
  const [y0r, y1r] = extent(ys);
  // 퇴화 구간(정고도 순항 등) 0-span 나눗셈 금지 — lineChartCanvas와 같은 정책
  const padOf = (lo, hi) => (lo < hi ? [lo - 0.06 * (hi - lo), hi + 0.06 * (hi - lo)]
    : [lo - 1, hi + 1]);
  const [x0, x1] = padOf(x0r, x1r);
  const [y0, y1] = padOf(y0r, y1r);
  const px = linScale(x0, x1, mL, width - mR);
  const py = linScale(y0, y1, height - mB, mT);

  ctx.strokeStyle = "#e5e5ea";
  ctx.beginPath();
  for (const tk of niceTicks(x0, x1, 5)) {
    ctx.moveTo(px(tk), mT);
    ctx.lineTo(px(tk), height - mB);
    ctx.fillStyle = "#86868b";
    ctx.fillText(fmtTick(tk), px(tk) - 12, height - mB + 13);
  }
  for (const tk of niceTicks(y0, y1, 4)) {
    ctx.moveTo(mL, py(tk));
    ctx.lineTo(width - mR, py(tk));
    ctx.fillStyle = "#86868b";
    ctx.fillText(fmtTick(tk), 4, py(tk) + 3);
  }
  ctx.stroke();
  ctx.fillStyle = "#86868b";
  ctx.fillText(xLabel, width - mR - 46, height - 4);
  ctx.fillText(yLabel, 4, mT - 6);

  // 웨이포인트 가로좌표 안내선 (고도 정보 없음 — 세로선만)
  ctx.strokeStyle = "#ffcc80";
  ctx.setLineDash([3, 3]);
  ctx.beginPath();
  for (const wx of wpXs) {
    if (typeof wx !== "number" || !Number.isFinite(wx)) continue;
    ctx.moveTo(px(wx), mT);
    ctx.lineTo(px(wx), height - mB);
  }
  ctx.stroke();
  ctx.setLineDash([]);

  ctx.strokeStyle = "#007aff";
  ctx.lineWidth = 1.6;
  ctx.beginPath();
  let started = false;
  xs.forEach((x, i) => {
    const y = ys[i];
    // 결측(직렬화 null·NaN)은 잇지 않고 끊는다 — 없는 구간을 직선으로 위조 금지
    if (typeof x !== "number" || typeof y !== "number"
      || !Number.isFinite(x) || !Number.isFinite(y)) { started = false; return; }
    if (!started) { ctx.moveTo(px(x), py(y)); started = true; }
    else ctx.lineTo(px(x), py(y));
  });
  ctx.stroke();

  if (typeof xs[0] === "number" && typeof ys[0] === "number") {
    ctx.fillStyle = "#34c759";
    ctx.beginPath();
    ctx.arc(px(xs[0]), py(ys[0]), 4, 0, 2 * Math.PI); // 시작점
    ctx.fill();
  }
  if (markerIdx != null && markerIdx < xs.length
    && typeof xs[markerIdx] === "number" && typeof ys[markerIdx] === "number") {
    ctx.fillStyle = "#ff3b30";
    ctx.beginPath();
    ctx.arc(px(xs[markerIdx]), py(ys[markerIdx]), 5, 0, 2 * Math.PI);
    ctx.fill();
  }
  return canvas;
}

/** 시간 가중 히스토그램 — bars: [{x0, x1, time, frac}] (lib/duty.js histBars).

x축 범위는 **막대 경계 그대로**다. 엔진이 한계를 알면 경계를 한계 전 구간으로
잡으므로, 빈 칸으로 남는 구간이 곧 "쓰지 않은 조종권"이다 — 데이터 범위로 다시
맞추면 어떤 런이든 양끝이 차 보여 여유가 사라진다.
markers: [{x, color, label, dash}] — 평균(트림 편향) 같은 세로 기준선.
*/
export function histogramCanvas(bars, {
  title = "", xLabel = "", yLabel = "체류 시간 [s]", markers = [],
  color = "#007aff", width = 380, height = 190,
} = {}) {
  const { canvas, ctx } = makeCanvas(width, height);
  const mL = 46, mT = 20, mR = 12, mB = 30;
  if (!bars.length) {
    ctx.fillStyle = "#86868b";
    ctx.fillText("표본 없음", mL, height / 2);
    return canvas;
  }
  const x0 = bars[0].x0;
  const x1 = bars[bars.length - 1].x1;
  const yMax = Math.max(...bars.map((b) => b.time), 1e-9);
  const px = linScale(x0, x1, mL, width - mR);
  const py = linScale(0, yMax * 1.08, height - mB, mT);

  ctx.strokeStyle = "#e5e5ea";
  ctx.beginPath();
  for (const tk of niceTicks(0, yMax, 4)) {
    ctx.moveTo(mL, py(tk));
    ctx.lineTo(width - mR, py(tk));
    ctx.fillStyle = "#86868b";
    ctx.fillText(fmtTick(tk), 4, py(tk) + 3);
  }
  ctx.stroke();

  ctx.fillStyle = color;
  for (const b of bars) {
    const w = Math.max(1, px(b.x1) - px(b.x0) - 1);
    const h = py(0) - py(b.time);
    if (h > 0) ctx.fillRect(px(b.x0), py(b.time), w, h);
  }

  for (const m of markers) {
    if (typeof m.x !== "number" || !Number.isFinite(m.x)) continue;
    ctx.strokeStyle = m.color ?? "#ff3b30";
    ctx.setLineDash(m.dash ?? [4, 3]);
    ctx.beginPath();
    ctx.moveTo(px(m.x), mT);
    ctx.lineTo(px(m.x), height - mB);
    ctx.stroke();
    ctx.setLineDash([]);
    if (m.label) {
      ctx.fillStyle = m.color ?? "#ff3b30";
      ctx.fillText(m.label, Math.min(px(m.x) + 3, width - mR - 40), mT + 10);
    }
  }

  ctx.fillStyle = "#86868b";
  for (const tk of niceTicks(x0, x1, 5)) {
    ctx.fillText(fmtTick(tk), px(tk) - 10, height - mB + 14);
  }
  ctx.fillText(xLabel, width - mR - 7 * xLabel.length, height - 4);
  ctx.fillText(yLabel, 4, mT - 6);
  ctx.fillStyle = "#1d1d1f";
  ctx.fillText(title, mL, 12);
  return canvas;
}

/** 타각–타율 체류시간 밀도 + 작동기 능력 상자.

view: {xEdges, yEdges, time[[…]]} (lib/duty.js densityView), box: capabilityBox 결과.
셀 색은 **√(시간) 비례**다: 듀티 분포는 트림점 한 칸에 시간이 몰려 선형 척도로
칠하면 나머지가 전부 배경색이 되어 "거기밖에 안 갔다"로 오독된다.
능력 상자(위치 한계 세로선·±rate_max 가로선)는 아는 변만 그린다 — 모르는 한계를
임의값으로 그리면 없는 정보를 그리는 것이다.
*/
export function densityCanvas(view, {
  box = {}, title = "", xLabel = "", yLabel = "", width = 380, height = 190,
} = {}) {
  const { canvas, ctx } = makeCanvas(width, height);
  const mL = 52, mT = 20, mR = 12, mB = 30;
  const xe = view?.xEdges ?? [];
  const ye = view?.yEdges ?? [];
  const cells = view?.time ?? [];
  if (xe.length < 2 || ye.length < 2) {
    ctx.fillStyle = "#86868b";
    ctx.fillText("표본 없음", mL, height / 2);
    return canvas;
  }
  const px = linScale(xe[0], xe[xe.length - 1], mL, width - mR);
  const py = linScale(ye[0], ye[ye.length - 1], height - mB, mT);
  let peak = 0;
  for (const row of cells) for (const v of row) if (v > peak) peak = v;

  for (let i = 0; i < cells.length; i += 1) {
    for (let j = 0; j < cells[i].length; j += 1) {
      const v = cells[i][j];
      if (!(v > 0)) continue; // 빈 셀은 칠하지 않는다 — "안 간 곳"이 보여야 한다
      const k = Math.sqrt(v / peak);
      ctx.fillStyle = `rgba(0, 113, 227, ${0.12 + 0.88 * k})`;
      const xa = px(xe[i]);
      const xb = px(xe[i + 1]);
      const ya = py(ye[j + 1]);
      const yb = py(ye[j]);
      ctx.fillRect(xa, ya, Math.max(1, xb - xa), Math.max(1, yb - ya));
    }
  }

  ctx.strokeStyle = "#e5e5ea";
  ctx.beginPath();
  for (const tk of niceTicks(ye[0], ye[ye.length - 1], 4)) {
    ctx.moveTo(mL, py(tk));
    ctx.lineTo(width - mR, py(tk));
    ctx.fillStyle = "#86868b";
    ctx.fillText(fmtTick(tk), 4, py(tk) + 3);
  }
  ctx.stroke();

  // 능력 상자 — 아는 변만 (null은 그리지 않는다)
  ctx.strokeStyle = "#ff3b30";
  ctx.setLineDash([5, 3]);
  ctx.beginPath();
  for (const x of [box.xLo, box.xHi]) {
    if (typeof x !== "number" || !Number.isFinite(x)) continue;
    ctx.moveTo(px(x), mT);
    ctx.lineTo(px(x), height - mB);
  }
  for (const y of [box.yLo, box.yHi]) {
    if (typeof y !== "number" || !Number.isFinite(y)) continue;
    ctx.moveTo(mL, py(y));
    ctx.lineTo(width - mR, py(y));
  }
  ctx.stroke();
  ctx.setLineDash([]);

  ctx.fillStyle = "#86868b";
  for (const tk of niceTicks(xe[0], xe[xe.length - 1], 5)) {
    ctx.fillText(fmtTick(tk), px(tk) - 10, height - mB + 14);
  }
  ctx.fillText(xLabel, width - mR - 7 * xLabel.length, height - 4);
  ctx.fillText(yLabel, 4, mT - 6);
  ctx.fillStyle = "#1d1d1f";
  ctx.fillText(title, mL, 12);
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
