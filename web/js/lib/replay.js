/** 재생 유틸 (02 §8 5단계) — stride 산정·모드 구간·극값 (순수 로직, 테스트 대상). */

export function strideFor(nTotal, target = 1500) {
  return Math.max(1, Math.ceil(nTotal / target));
}

/** 엔벨로프 플래그 이름(한국어) — 엔진 flags 키와 1:1 (simulator._envelope). */
export const FLAG_LABEL = {
  alpha: "α", beta: "β", mach: "마하", altitude: "고도",
};

/** 실제로 뜬 플래그 이름만 나열 — any_flag 하나로 뭉뚱그리면 기준면 이탈(고도)이
DB 유효범위 이탈로 오독된다. 미정의 키는 원래 이름으로 통과(엔진 확장에 안전). */
export function flaggedNames(env) {
  const hit = Object.entries(env?.flags ?? {})
    .filter(([, arr]) => Array.isArray(arr) && arr.some(Boolean))
    .map(([k]) => FLAG_LABEL[k] ?? k);
  return hit.length ? hit.join("·") : "—";
}

/** 모드 문자열 시계열 → 연속 구간 [{mode, i0, i1}] (i1 배타) — 배경 밴드용. */
export function modeSpans(modes) {
  const spans = [];
  for (let i = 0; i < modes.length; i += 1) {
    if (!spans.length || spans[spans.length - 1].mode !== modes[i]) {
      if (spans.length) spans[spans.length - 1].i1 = i;
      spans.push({ mode: modes[i], i0: i, i1: modes.length });
    }
  }
  return spans;
}

/** null(NaN 직렬화) 무시 극값 — 전부 null이면 [0, 1] 안전 기본. */
export function extent(arr) {
  let lo = Infinity;
  let hi = -Infinity;
  for (const v of arr) {
    if (typeof v !== "number") continue;
    if (v < lo) lo = v;
    if (v > hi) hi = v;
  }
  return lo <= hi ? [lo, hi] : [0, 1];
}
