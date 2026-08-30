/** 엔벨로프 lib (01 §2.6) — 설계 엔벨로프 응답의 표현 변환 (뷰·캔버스와 분리, 테스트 대상).

수치·합성·귀속은 전부 엔진(design_envelope·envelope_verdict) — 여기서는
다각형 조립·구간 병합·판정 셀 분류·프리필 판단만. 서버가 준 필드를 다시
계산하지 않는다. 모르는 귀속·사유 코드는 코드 그대로 표시한다 (조용히
숨기면 엔진이 코드를 늘렸을 때 화면이 거짓말을 한다).
*/

import { STATUS } from "./plot.js";

// ── 경계 귀속 (엔진 lo_source/hi_source 코드가 정본) ──────────────────────
export const BOUND_META = {
  stall: { label: "실속 한계 (공력)", color: "#ff3b30" },
  db: { label: "공력 DB 범위", color: "#af52de" },
  stall_table: { label: "실속표 축 상한 (공력)", color: "#5856d6" },
  mach_no: { label: "M_NO (구조)", color: "#c93400" },
  qbar: { label: "q̄ 한계 (구조)", color: "#ff9500" },
};

export const boundLabel = (code) => BOUND_META[code]?.label ?? code;
export const boundColor = (code) => BOUND_META[code]?.color ?? "#8e8e93";

/** region → 채움 다각형 목록 [[{mach, alt}, …], …] — empty 행에서 분할.
 * lo 곡선을 고도 오름차순으로, hi 곡선을 내림차순으로 이어 폐곡선. 한 행짜리
 * 조각은 면이 못 되므로 버린다 (경계선 세그먼트는 별도로 남는다). */
export function regionPolygons(region) {
  const polys = [];
  let run = [];
  const flush = () => {
    if (run.length >= 2) {
      polys.push([
        ...run.map((i) => ({ mach: region.mach_lo[i], alt: region.alt[i] })),
        ...[...run].reverse().map((i) => ({ mach: region.mach_hi[i], alt: region.alt[i] })),
      ]);
    }
    run = [];
  };
  region.alt.forEach((_, i) => {
    if (region.empty[i]) flush();
    else run.push(i);
  });
  flush();
  return polys;
}

/** region → 귀속별 경계선 세그먼트 [{source, side, pts}] — side "lo"|"hi".
 * 같은 source 연속 행을 병합하고, source가 바뀌는 지점은 직전 점을 공유해
 * 곡선이 끊겨 보이지 않게 한다. empty 행은 세그먼트를 끊는다 (가짜 연결선 금지). */
export function boundarySegments(region) {
  const out = [];
  for (const side of ["lo", "hi"]) {
    const srcArr = region[`${side}_source`];
    const machArr = side === "lo" ? region.mach_lo : region.mach_hi;
    let cur = null;
    let prevPt = null;
    region.alt.forEach((alt, i) => {
      if (region.empty[i]) {
        cur = null;
        prevPt = null;
        return;
      }
      const pt = { mach: machArr[i], alt };
      if (!cur || cur.source !== srcArr[i]) {
        cur = { source: srcArr[i], side, pts: prevPt ? [prevPt] : [] };
        out.push(cur);
      }
      cur.pts.push(pt);
      prevPt = pt;
    });
  }
  return out;
}

// ── 제어 가능 영역 스캔 (엔진 envelope_verdict 사유 코드가 정본) ──────────
export const KIND_META = {
  ok: { label: "제어 가능 (트림 성립)", color: STATUS.ok },
  not_converged: { label: "트림 미수렴", color: STATUS.na },
  alpha_margin: { label: "α 여유 부족 (실속 근접)", color: STATUS.bad },
  saturated_throttle_high: { label: "스로틀 상한 포화 (추진 한계)", color: "#ff9500" },
  saturated_de: { label: "타면 포화", color: "#ffcc00" },
  saturated_throttle_low: { label: "스로틀 하한 포화 (아이들)", color: "#5ac8fa" },
};

export const kindLabel = (kind) => KIND_META[kind]?.label ?? kind;
export const kindColor = (kind) => KIND_META[kind]?.color ?? "#8e8e93";

/** 스캔 entries → 판정 셀 {mach, alt, fuel, ok, kind}.
 * kind는 엔진 reasons의 첫 항목(우선순위 대표 — points.envelope_verdict 순서).
 * 실패인데 사유가 비면 "unknown" — 성공으로 위장하지 않는다. */
export function scanCells(entries) {
  return entries.map((e) => ({
    mach: e.trim.case.mach,
    alt: e.trim.case.alt,
    fuel: e.trim.case.fuel,
    ok: e.verdict.ok === true,
    kind: e.verdict.ok === true ? "ok" : (e.verdict.reasons?.[0] ?? "unknown"),
  }));
}

const KIND_ORDER = [
  "not_converged", "alpha_margin", "saturated_throttle_high",
  "saturated_de", "saturated_throttle_low",
];

/** 판정 셀 → 종류별 집계 {total, ok, byKind: [{kind, n}]} — byKind는 실패만,
 * 엔진 우선순위 순. 미정의 코드는 뒤에 그대로 덧붙인다. */
export function scanSummary(cells) {
  const counts = new Map();
  for (const c of cells) counts.set(c.kind, (counts.get(c.kind) ?? 0) + 1);
  const byKind = [];
  for (const k of KIND_ORDER) {
    if (counts.has(k)) byKind.push({ kind: k, n: counts.get(k) });
  }
  for (const [k, n] of counts) {
    if (k !== "ok" && !KIND_ORDER.includes(k)) byKind.push({ kind: k, n });
  }
  return { total: cells.length, ok: counts.get("ok") ?? 0, byKind };
}

/** 추진 히트맵 셀 — 트림 스로틀 소요(연속 색: 초록→주황) + 포화·불가 구분.
 * 판정 문턱을 여기서 만들지 않는다 — 포화 여부는 엔진 verdict 사유가 정본,
 * 색 그라데이션은 소요량의 표시일 뿐이다. */
export function throttleCell(entry) {
  if (!entry.trim.converged) {
    return { color: STATUS.na, text: "불가" };
  }
  const thr = entry.trim.control.throttle[0];
  const pct = `${Math.round(thr * 100)}%`;
  if (entry.verdict.reasons?.includes("saturated_throttle_high")) {
    return { color: STATUS.bad, text: `${pct} 포화` };
  }
  const t = Math.min(1, Math.max(0, thr));
  return { color: `hsl(${Math.round(130 - 100 * t)}, 65%, 42%)`, text: pct };
}

// ── 필요값 폼 (02 §5.5 — 웹은 엔진 기본값을 재기술하지 않는다) ────────────

/** 프리필 자기 정렬 — 사용자가 손댄 필드는 유지, 아니면 서버 echo로 갱신.
 * incoming null(경계 없음·미지정)은 빈칸. */
export function prefillValue(currentStr, touched, incoming) {
  if (touched) return currentStr;
  return incoming == null ? "" : String(incoming);
}

/** 옵션 수치 입력 — 빈칸은 null(파라미터 생략 = 서버 None 계약), 비유한값은 던진다. */
export function optNum(str, label = "값") {
  const s = String(str ?? "").trim();
  if (s === "") return null;
  const v = Number(s);
  if (!Number.isFinite(v)) throw new Error(`${label}이(가) 숫자가 아님: ${str}`);
  return v;
}

/** 쿼리 문자열 — null/undefined 생략 (서버 None = 데모 프로파일/경계 없음 계약).
 * 값을 보내는 순간 limits_source가 user-input이 되므로, 손대지 않은 필드는
 * 호출측이 null로 넘겨야 한다. */
export function envelopeQuery(params) {
  return Object.entries(params)
    .filter(([, v]) => v !== null && v !== undefined)
    .map(([k, v]) => `${k}=${encodeURIComponent(v)}`)
    .join("&");
}
