/** 트림 격자 생성 (02 §8 2단계) — 케이스 매트릭스의 순수 로직 (뷰와 분리, 테스트 대상).

리스트상 인접 = 물리 인접이 되도록 서펜타인 순서를 만든다 — 엔진 trim_batch의
인접 케이스 시드·연속성 판정 전제 (01 §4.1).
*/

export function machRange(from, to, step) {
  if (!(step > 0) || !(to >= from)) {
    throw new Error(`잘못된 마하 범위: ${from}~${to} step ${step}`);
  }
  const out = [];
  for (let k = 0; ; k += 1) {
    const v = Math.round((from + k * step) * 1e9) / 1e9; // 부동소수 오차 제거
    if (v > to + 1e-9) break;
    out.push(v);
    if (out.length > 10000) throw new Error("마하 격자가 너무 큼 (10000점 초과)");
  }
  return out;
}

export function serpentineCases(machs, alts, fuels) {
  const cases = [];
  let row = 0;
  for (const fuel of fuels) {
    for (const alt of alts) {
      const ms = row % 2 === 0 ? machs : [...machs].reverse();
      for (const mach of ms) cases.push({ mach, alt, fuel });
      row += 1;
    }
  }
  return cases;
}

export function parseNumberList(text) {
  const vals = String(text).split(/[\s,]+/).filter(Boolean).map(Number);
  if (!vals.length || vals.some((v) => !Number.isFinite(v))) {
    throw new Error(`수치 목록이 아님: ${text}`);
  }
  return vals;
}
