/** 트림 격자 생성 (02 §8 3단계) — 케이스 매트릭스의 순수 로직 (뷰와 분리, 테스트 대상).

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
 * 뒤집혀 있고, 그 순서로 세로 표를 그리면 마하가 0.3→0.55→0.55→0.3으로 왕복해
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


// ── 탭의 기본 격자는 여기 없다 (05 §11.13 5단계) ──────────────────────────────────────────
// 마진 맵·게인 카드·흐름 평가·영향성은 전부 서버 `POST /grid/base`(요구영역의 기본 격자)의 보낼 수 있는 점을 쓴다
// (lib/opspace.js defaultRoleSelection). 예제 기체 격자를 웹 상수로 들고 다니던 폴백은 폐지했다 — 요구영역이 미정의면
// 템플릿 격자로 되돌아가지 않고 보내지 않는다. 다시 세우지 않는다(grid.test.js 가드).


// ── 대표 부분 격자 — 템플릿 격자(마하 등간격 × 고도 × 연료)에서 n건 ────────────────────────────────
// **영향성 탭은 더 쓰지 않는다**(이관 5단계 — 요구영역 기본 격자의 점을 고른다, 대표점 규칙은 lib/opspace.js
// representativePoints). 남은 까닭은 기록이다: 쇼케이스 결함 창은 이 함수가 S1 템플릿 격자에서 고른 네 점(n=4)에서
// 쟀고, showcase.test.js가 그 이름이 SHOWCASE_EVAL_POINTS와 같은 문자열임을 대조한다.
// 고르는 순서는 축마다 **끝점부터**다: 마하 양끝(동압 최저·최고 — 게인 스케줄이 가장 멀리 가는 자리) → 고도 양끝 →
// 연료 양끝 → 그다음 가운데. 한 축에 하나만 남기면 가운데 값이다.

/** 목록에서 k개 — 1이면 가운데, 2 이상이면 양끝을 포함한 등간격 첨자. */
function pickSpread(list, k) {
  if (k <= 1) return [list[Math.floor((list.length - 1) / 2)]];
  const idx = [];
  for (let i = 0; i < k; i += 1) idx.push(Math.round((i * (list.length - 1)) / (k - 1)));
  return [...new Set(idx)].map((i) => list[i]);
}

/** 마하 k점이 **등간격으로** 뽑히는가 — 부분 격자가 from·to·step 세 칸으로 적혀야 한다. */
const machPickable = (len, k) => k === 1 || (k >= 2 && k <= len && (len - 1) % (k - 1) === 0);

/** 격자(수치 {machFrom, machTo, machStep, alts, fuels} — 템플릿 trim_grid 꼴, 인자로만 받는다) → n건 이하의 대표 부분 격자(같은 모양).
 *  n이 격자 전체 이상이면 격자 그대로다. 케이스 이름은 원 격자와 같다(nameCases — 값 그대로 문자열화). */
export function representativeGrid(grid, n) {
  if (!Number.isInteger(n) || n < 1) throw new Error(`대표 케이스 수는 1 이상의 정수: ${n}`);
  const machs = machRange(grid.machFrom, grid.machTo, grid.machStep);
  if (!grid.alts.length || !grid.fuels.length) throw new Error("격자 목록이 비었다 — 고도·연료를 하나 이상 적는다");
  if (machs.length * grid.alts.length * grid.fuels.length <= n) {
    return { machFrom: grid.machFrom, machTo: grid.machTo, machStep: grid.machStep,
      alts: [...grid.alts], fuels: [...grid.fuels] };
  }
  // 「양끝」은 값의 양끝이다 — 목록이 적힌 순서(템플릿은 손으로 쓴다)의 첫·끝이 아니다. 마하는 등간격이라 이미 오름차순
  const asc = (xs) => [...xs].sort((a, b) => a - b);
  const axes = { mach: machs, alt: asc(grid.alts), fuel: asc(grid.fuels) };
  const k = { mach: 1, alt: 1, fuel: 1 };
  const nextK = (ax) => {
    const len = axes[ax].length;
    for (let c = k[ax] + 1; c <= len; c += 1) {
      if (ax !== "mach" || machPickable(len, c)) return c;
    }
    return null;
  };
  for (let grew = true; grew;) {
    grew = false;
    for (const ax of ["mach", "alt", "fuel"]) {
      const c = nextK(ax);
      if (c == null) continue;
      const count = Object.entries(k).reduce((p, [a, v]) => p * (a === ax ? c : v), 1);
      if (count > n) continue;
      k[ax] = c;
      grew = true;
    }
  }
  const ms = pickSpread(machs, k.mach);
  const step = ms.length > 1
    ? Math.round(((ms[ms.length - 1] - ms[0]) / (ms.length - 1)) * 1e9) / 1e9
    : grid.machStep;
  return { machFrom: ms[0], machTo: ms[ms.length - 1], machStep: step,
    alts: pickSpread(axes.alt, k.alt), fuels: pickSpread(axes.fuel, k.fuel) };
}
