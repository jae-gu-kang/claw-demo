/** 웨이포인트 지도 편집기 수치 계층 — 뷰 상태 {cN, cE, span} ↔ 픽셀 사상·역사상.

좌표 규약은 views/plots.js trackCanvas와 동일: E→x(우), N→y(상), 등축(단일
kScale). 여기는 DOM 무접촉 순수 함수만 — 캔버스·포인터 이벤트는 views/wpmap.js.
*/

import { linScale } from "./plot.js";

export const DRAG_PX = 5; // 클릭↔드래그 판별 임계 [px]
// 휠 한 이벤트당 줌 배율. 종전 1.2는 **이벤트당**이라 트랙패드처럼 한 제스처에
// 수십 개가 오는 입력에서 한 번 굴릴 때마다 지도가 너무 크거나 너무 작아졌다
// (사용자 제기). 로그 줌 기준으로 100배 둔하게 — 지수만 고치면 되도록 남긴다.
export const WHEEL_ZOOM_DIVISOR = 100;
export const ZOOM_STEP = 1.2 ** (1 / WHEEL_ZOOM_DIVISOR);
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
    const sd = String(r.d ?? "").trim();
    const n = Number(sn), e = Number(se), d = Number(sd);
    const ok = sn !== "" && se !== "" && Number.isFinite(n) && Number.isFinite(e);
    // 고도는 선택 — 빈 칸/비수치는 null(고도 없음)이지 0이 아니다. 0으로 두면
    // 세로 프로파일이 사용자가 넣지 않은 해면 고도를 넣은 것처럼 그린다
    return { n, e, ok, d: sd !== "" && Number.isFinite(d) ? d : null };
  });
}

/** 계획 세로 프로파일 — [{dist, alt, idx, mark}] (거리 = 출발점부터의 누적 **수평** 거리).
 *
 * mark: "start" 출발점 · "wp" 웨이포인트 중심 · "ramp" 램프 꼭대기.
 * idx는 웨이포인트 번호("wp"만 ≥0). 고도가 없는 점은 alt: null로 남긴다 —
 * 이웃 값으로 메우면 화면이 사용자가 넣지 않은 고도를 넣은 것처럼 그린다.
 * 출발점 고도(startAlt)는 시뮬 시작 트림 고도다: 엔진 LosPath도 첫 구간을
 * **첫 스텝의 기체 고도**에서 시작하므로 둘이 같은 점에서 출발한다.
 *
 * acceptRadius를 주면 **엔진 명령과 같은 모양**이 된다. 엔진 램프는 웨이포인트
 * 중심이 아니라 도달 반경 경계에서 끝나고(guidance/path.py _leg_alt) 거기서
 * 다음 구간으로 전환하므로, 중심까지 곧게 이으면 화면이 구간 내내 명령보다
 * 뒤처진 기울기를 그린다 — 최대 Δalt·r/seg 어긋난다(리뷰 실측: 8 km 구간·반경
 * 200 m·Δ500 m에서 12.5 m, 500 m 구간에서는 200 m). 램프 꼭대기 점을 하나 더
 * 찍어 평평한 마루를 그리면 그 어긋남이 없어진다. 0이면 종전대로 중심끼리 잇는다
 * (반경을 모르는 호출측을 위한 폴백 — 그 경우 위 어긋남이 남는다).
 *
 * [남은 어긋남] 웨이포인트를 도달 반경보다 **촘촘히** 찍어 중간 구간이 seg ≤ r로
 * 퇴화하면, 그 계단의 x가 r만큼 늦다: 엔진은 직전 웨이포인트 반경 진입(cum−r)에서
 * 그 구간을 활성화하는데 여기서는 직전 중심(cum)에 찍는다. 비퇴화 구간에서는
 * 활성화 직후 명령이 wa_prev로 클램프돼 화면의 마루와 겹치므로 보이지 않고,
 * 첫 구간이 퇴화면 활성화가 cum 0이라 일치한다 — 중간 퇴화 구간 하나뿐이다.
 * 고치려면 퇴화 구간의 마루를 직전 구간의 마루 x로 이어 나르면 된다(리뷰 제안).
 */
export function planProfile(points, startAlt = null, acceptRadius = 0) {
  const out = [{ dist: 0, alt: startAlt, idx: -1, mark: "start" }];
  let dist = 0;
  let pn = 0, pe = 0;
  points.forEach((p, i) => {
    if (!p.ok) return; // 표시 불가 행은 거리 누적에서도 빠진다 (지도와 같은 규칙)
    const seg = Math.hypot(p.n - pn, p.e - pe);
    // 램프 꼭대기 — 구간이 반경보다 짧으면 이을 자리가 없어 구간 시작에서 곧바로
    // 목표 고도다(엔진 denom <= 0 분기와 같은 퇴화). 그때 두 점이 같은 x가 되어
    // 화면에 수직 계단으로 그려지는데, 그것이 실제 명령이다
    const top = dist + Math.max(0, seg - acceptRadius);
    dist += seg;
    pn = p.n; pe = p.e;
    if (acceptRadius > 0 && p.d != null) out.push({ dist: top, alt: p.d, idx: -1, mark: "ramp" });
    out.push({ dist, alt: p.d, idx: i, mark: "wp" });
  });
  return out;
}

/** 실측 세로 프로파일 — 궤적 (pn, pe, h) → [{dist, alt}] 누적 수평거리 기준.
 * 비수치 샘플에서 끊지 않고 **건너뛴다** — 거리 누적이 그 구간만큼 짧아지는 것이
 * 없는 점을 이어 그리는 것보다 낫다(끊으면 x가 뒤로 감기어 곡선이 접힌다). */
export function trackProfile(pn, pe, h) {
  const out = [];
  let dist = 0;
  let ln = null, le = null;
  for (let i = 0; i < pn.length; i += 1) {
    const n = pn[i], e = pe[i], a = h?.[i];
    if (typeof n !== "number" || typeof e !== "number" || !Number.isFinite(n) || !Number.isFinite(e)) continue;
    if (ln !== null) dist += Math.hypot(n - ln, e - le);
    ln = n; le = e;
    if (typeof a === "number" && Number.isFinite(a)) out.push({ dist, alt: a });
  }
  return out;
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
