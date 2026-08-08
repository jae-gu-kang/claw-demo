/** 재생 유틸 (02 §8 5단계) — stride 산정·모드 구간·극값 (순수 로직, 테스트 대상). */

export function strideFor(nTotal, target = 1500) {
  return Math.max(1, Math.ceil(nTotal / target));
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
