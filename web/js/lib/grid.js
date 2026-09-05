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

/** 케이스에 정본 이름 부여 — 이름이 케이스 매핑 키다 (영향성 스캔의 bad_cases ↔
3단 B 케이스 객체 복원). 반올림하지 않고 격자 값 그대로 문자열화한다 — 정밀 격자
(예: mach 간격 0.005)에서 반올림 이름은 겹치고, 겹친 이름은 Δ의 base 귀속을
조용히 다른 케이스로 바꾼다. 중복은 던진다 (조용한 오귀속 금지). */
export function nameCases(cases) {
  const seen = new Set();
  return cases.map((c) => {
    const name = `M${c.mach}_h${c.alt}_f${c.fuel}`;
    if (seen.has(name)) {
      throw new Error(`케이스 이름 중복: ${name} — 격자 목록에 같은 값이 두 번 있다`);
    }
    seen.add(name);
    return { ...c, name }; // 입력의 name이 검증한 이름을 덮지 않도록 뒤에 둔다
  });
}

export function parseNumberList(text) {
  const vals = String(text).split(/[\s,]+/).filter(Boolean).map(Number);
  if (!vals.length || vals.some((v) => !Number.isFinite(v))) {
    throw new Error(`수치 목록이 아님: ${text}`);
  }
  return vals;
}

/** 케이스 이름 → 격자 좌표 — `nameCases`의 역함수. 형식이 아니면 null.
 *
 * 이름이 값 그대로라(위 nameCases) 되돌릴 수 있다. 되돌리는 쪽이 필요한 이유는
 * **표의 행 순서**다: 실행 순서는 서펜타인(인접 트림 시드)이라 마하가 줄마다
 * 뒤집혀 있고, 그 순서로 세로 표를 그리면 마하가 0.4→0.8→0.8→0.4로 왕복해
 * "고도가 오르면 이쪽으로 간다" 같은 경향이 눈에 안 잡힌다.
 */
export function parseCaseName(name) {
  const m = /^M(-?[\d.]+(?:[eE][+-]?\d+)?)_h(-?[\d.]+(?:[eE][+-]?\d+)?)_f(-?[\d.]+(?:[eE][+-]?\d+)?)$/
    .exec(String(name ?? ""));
  if (!m) return null;
  const [mach, alt, fuel] = m.slice(1).map(Number);
  if (![mach, alt, fuel].every(Number.isFinite)) return null;
  return { mach, alt, fuel };
}

/** 표 행 순서 — (fuel, alt, mach) 오름차순. **하나라도 못 읽으면 원래 순서 그대로**:
 *  절반만 정렬하면 비교자가 비일관(a=b, b=c인데 a≠c)이 되어 순서가 엔진 재량이 된다. */
export function orderCaseNames(names) {
  const list = [...(names ?? [])];
  const coords = list.map(parseCaseName);
  if (coords.some((c) => c === null)) return list;
  const key = new Map(list.map((n, i) => [n, coords[i]]));
  return list.sort((a, b) => {
    const pa = key.get(a);
    const pb = key.get(b);
    return pa.fuel - pb.fuel || pa.alt - pb.alt || pa.mach - pb.mach;
  });
}


// ── 기본 케이스 격자 — **한 곳 정의** (02 §5.5) ──────────────────────────────
// 영향성 탭의 격자 폼 기본값과 게인 탭 지표 카드의 격자가 같은 값이어야 한다 —
// 두 화면이 "기본 격자"라며 다른 격자를 돌리면 최악 운용점이 화면마다 달라진다.
// 값 자체는 마진 맵 시연 격자(15케이스)와 같은 데모 기본이다.
export const DEFAULT_GRID = {
  machFrom: 0.4, machTo: 0.8, machStep: 0.1,
  alts: [100, 1000, 3000], fuels: [200],
};

/** 기본 격자의 이름 붙은 케이스 15건 — 실행 순서는 서펜타인(인접 트림 시드). */
export function defaultGridCases() {
  return nameCases(serpentineCases(
    machRange(DEFAULT_GRID.machFrom, DEFAULT_GRID.machTo, DEFAULT_GRID.machStep),
    DEFAULT_GRID.alts, DEFAULT_GRID.fuels));
}
