/** 웨이포인트 지도 편집기 수치 계층 — 뷰 상태 {cN, cE, span} ↔ 픽셀 사상·역사상.

좌표 규약은 views/plots.js trackCanvas와 동일: E→x(우), N→y(상), 등축(단일
kScale). 여기는 DOM 무접촉 순수 함수만 — 캔버스·포인터 이벤트는 views/wpmap.js.
*/

import { linScale } from "./plot.js";

export const DRAG_PX = 5; // 클릭↔드래그 판별 임계 [px]
export const SPAN_MIN = 50; // 줌 인 한계 [m]
export const SPAN_MAX = 1e6; // 줌 아웃 한계 [m]
export const DEFAULT_SPAN = 20000; // 빈 목록 초기 뷰 [m] — 기본 미션 스케일

/** [[n,e],...] 전부 포함하는 등축 초기 뷰 — 빈 목록은 원점 기본 뷰. */
export function fitView(points, { pad = 1.15, minSpan = 200 } = {}) {
  if (!points.length) return { cN: 0, cE: 0, span: DEFAULT_SPAN };
  const ns = points.map((p) => p[0]);
  const es = points.map((p) => p[1]);
  const n0 = Math.min(...ns), n1 = Math.max(...ns);
  const e0 = Math.min(...es), e1 = Math.max(...es);
  // 퇴화(단일점·전부 동일)에서 0-span 나눗셈 금지 — minSpan 하한
  const span = Math.max((Math.max(n1 - n0, e1 - e0)) * pad, minSpan);
  return { cN: (n0 + n1) / 2, cE: (e0 + e1) / 2, span };
}

/** 등축 투영기 — margin 안쪽 정사각 영역에 사상 (trackCanvas 규약). */
export function makeProjection(view, width, height, margin = 42) {
  const { cN, cE, span } = view;
  const px = linScale(cE - span / 2, cE + span / 2, margin, width - margin);
  const py = linScale(cN - span / 2, cN + span / 2, height - margin, margin);
  const kScale = (width - 2 * margin) / span; // m → px
  return {
    toPx: (n, e) => ({ x: px(e), y: py(n) }),
    toNed: (x, y) => ({
      n: cN - span / 2 + ((height - margin - y) / (height - 2 * margin)) * span,
      e: cE - span / 2 + ((x - margin) / (width - 2 * margin)) * span,
    }),
    kScale,
  };
}

/** 커서 중심 줌 — cursorNed({n,e})가 화면상 같은 자리에 남도록 중심 보정.

span 클램프로 factor가 잘리면 중심 보정도 잘린 비율 기준 — 아니면 한계
줌에서 지도가 커서 쪽으로 미끄러진다. 순수(입력 뷰 불변).
*/
export function zoomAt(view, factor, cursorNed, { minSpan = SPAN_MIN, maxSpan = SPAN_MAX } = {}) {
  const span = Math.min(Math.max(view.span / factor, minSpan), maxSpan);
  const k = span / view.span; // 실효 축소 비율 (클램프 반영)
  return {
    cN: cursorNed.n + (view.cN - cursorNed.n) * k,
    cE: cursorNed.e + (view.cE - cursorNed.e) * k,
    span,
  };
}

/** 팬 — 화면 픽셀 델타만큼 지도가 따라오도록 중심 이동 (y는 화면↓=북↓ 반전). */
export function panBy(view, dxPx, dyPx, kScale) {
  return {
    cN: view.cN + dyPx / kScale,
    cE: view.cE - dxPx / kScale,
    span: view.span,
  };
}

/** 픽셀 좌표에서 WP 찾기 — 뒤 인덱스(위에 그려진 것) 우선, ok:false 무시. */
export function hitTest(points, x, y, toPx, { radiusPx = 10 } = {}) {
  for (let i = points.length - 1; i >= 0; i--) {
    const p = points[i];
    if (!p.ok) continue;
    const { x: wx, y: wy } = toPx(p.n, p.e);
    if (Math.hypot(wx - x, wy - y) <= radiusPx) return i;
  }
  return -1;
}

/** 클라이언트 좌표 → 캔버스 논리 px — CSS max-width 축소(rect≠논리 크기) 보정. */
export function toCanvasXY(clientX, clientY, rect, width, height) {
  return {
    x: (clientX - rect.left) * (width / rect.width),
    y: (clientY - rect.top) * (height / rect.height),
  };
}

/** 문자열 행 → 수치 점 (행 순서·길이 보존) — 빈·비수치는 ok:false로 표시만 제외.

Number("") === 0 함정: 빈 칸이 원점 WP로 조용히 그려지면 안 된다 (lib/mission.js
num()과 같은 이유 — 거기는 제출 시점 throw, 여기는 표시 제외).
*/
export function rowsToPoints(rows) {
  return rows.map((r) => {
    const sn = String(r.n).trim(), se = String(r.e).trim();
    const n = Number(sn), e = Number(se);
    const ok = sn !== "" && se !== "" && Number.isFinite(n) && Number.isFinite(e);
    return { n, e, ok };
  });
}

/** 드래그 판별 — 시작점 대비 이동량이 임계 초과인가. */
export function isDrag(dx, dy, threshold = DRAG_PX) {
  return Math.hypot(dx, dy) > threshold;
}

/** 방문 순서 재배열 — rows[from]을 to로 이동(제자리 변이, 표 관행). 범위 밖 무변경. */
export function moveWaypoint(rows, from, to) {
  if (from === to || from < 0 || to < 0 || from >= rows.length || to >= rows.length) return false;
  const [row] = rows.splice(from, 1);
  rows.splice(to, 0, row);
  return true;
}

/** 지도발 좌표 → 표 문자열 — 1 m 반올림 + -0 정규화 (표 문자열 오염 방지). */
export function fmtMeters(v) {
  return String(Math.round(v) + 0);
}
