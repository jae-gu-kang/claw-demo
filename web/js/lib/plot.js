/** 플롯 수치 계층 (뷰·캔버스와 분리, 테스트 대상) — 스케일·눈금·상태색·격자 피벗.

마진 맵 시각화(02 §4)의 수치 부분. 캔버스 그리기 자체는 views/plots.js.
*/

export function linScale(d0, d1, r0, r1) {
  const k = (r1 - r0) / (d1 - d0 || 1);
  return (v) => r0 + (v - d0) * k;
}

export function niceTicks(min, max, n = 5) {
  if (!(max > min)) return [min];
  const span = max - min;
  const step0 = span / Math.max(1, n);
  const mag = 10 ** Math.floor(Math.log10(step0));
  const step = [1, 2, 5, 10].map((m) => m * mag).find((s) => span / s <= n) ?? 10 * mag;
  const out = [];
  for (let v = Math.ceil(min / step - 1e-9) * step; v <= max + 1e-9; v += step) {
    const t = Math.round(v * 1e9) / 1e9;
    out.push(t === 0 ? 0 : t); // -0 정규화 (ceil의 음의 영)
  }
  return out;
}

/** PM[deg] → 상태색 — 관례 여유 기준 [기본값]: ≥45° 양호, 30~45° 주의, <30° 부족.
 * 합격기준 수치는 파라미터 관리 계층 확정 시 그쪽이 정본 (02 §5.5). */
export function marginColor(pm) {
  if (pm === "inf") return "#157f3d";
  if (typeof pm !== "number") return "#9aa3ad"; // null(NaN)·문자열 — 판정 불가
  if (pm < 30) return "#c22f2f";
  if (pm < 45) return "#b57908";
  return "#157f3d";
}

/** margin-map entries → 연료 고정 (mach×alt) 격자 조회. */
export function pivotCases(entries, fuel) {
  const sel = entries.filter((e) => e.trim.case.fuel === fuel);
  const machs = [...new Set(sel.map((e) => e.trim.case.mach))].sort((a, b) => a - b);
  const alts = [...new Set(sel.map((e) => e.trim.case.alt))].sort((a, b) => a - b);
  const map = new Map(sel.map((e) => [`${e.trim.case.mach}|${e.trim.case.alt}`, e]));
  return { machs, alts, at: (m, a) => map.get(`${m}|${a}`) ?? null };
}

export function fuelsOf(entries) {
  return [...new Set(entries.map((e) => e.trim.case.fuel))].sort((a, b) => a - b);
}
