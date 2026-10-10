/** 해수면 판정 — 지형 팩 격자에서 "여기가 바다인가"를 낸다 (NED·m, 렌더러 무관).
 *
 * ## 표고만으로는 못 가린다 — 실측으로 확인했다
 *
 * 첫 설계는 "표고 ≤ 0이면 바다"였다. **그대로 그리면 활주로가 물에 잠긴다.**
 *
 *     활주로 남단 (0,0)   표고 0.00 m
 *     활주로 중앙         표고 0.00 m
 *     남쪽 8 km          표고 0.00 m      ← 구분이 안 된다
 *     core 티어의 37.4%가 정확히 0
 *
 * `scripts/terrain/build_terrain.py`의 `max(z, SEA_LEVEL)`가 **보간 전에** 자르기
 * 때문이다. 해수면 근처 육지(간척지·저지대)와 진짜 바다가 같은 값이 된다. 원자료로
 * 올라가도 안 된다 — terrarium 타일은 수심을 안 싣는다(먼바다 타일의 93.3%가 정확히 0).
 *
 * ## 되는 방법: 경계 연결 성분
 *
 * 바다는 **도메인 가장자리에 연결된** 0-성분이다. 육지에 흩뿌려진 0 m 셀은 양자화
 * 잡음이고 가장자리에 안 닿으므로 자동으로 육지로 남는다. 실측(core 티어):
 *
 *     바다로 판정            221,449 셀 = 199.3 km²
 *     0인데 육지로 남음       18,283 셀 =  16.5 km²   ← 활주로가 여기 있다
 *     활주로가 속한 0-성분        87 셀 =  0.08 km²   바다 미연결 ✓
 *
 * ## 티어를 따로 흘리면 안 된다
 *
 * core 경계(12 km)는 동쪽이 산지다. core만 자기 경계에서 흘리면 **바깥으로만 연결된
 * 만**이 통째로 빠진다. 그래서 넓은 티어를 먼저 흘리고, 그 결과를 좁은 티어의 시드로
 * 준다 — 티어 경계에서 해안선이 어긋나지 않는다.
 *
 * ## 결측은 바다가 아니다
 *
 * 관측이 없는 곳에 없는 바다를 만들지 않는다. `terrainpack.js`가 구멍을 구멍으로
 * 두는 것과 같은 규약이다.
 *
 * ## 해안 턱 흡수 — 흘린 **뒤에**, 흘리지 않는 규칙으로
 *
 * 원자료는 섬·해안에서 바다 쪽으로 100~300 m 떨어진 자리에 **폭 1~6칸, 높이 2.5 m 이하의
 * 격자 무늬 고리**를 싣고 있다(얕은 바다를 거친 표고로 메운 흔적). 표고 0이 아니라 흘리기가
 * 멈추므로 뭍으로 남았고, 화면에서는 해안마다 바다로 튀어나온 계단판과 그 윤곽을 따라
 * 그려진 파도 거품 띠로 보였다.
 *
 * 문턱을 올려 흘리면 안 된다 — **1 m만 올려도 활주로 180칸 중 121칸이 잠긴다**(실측). 간척지가
 * 1 m 아래 칸으로 바다와 이어져 있기 때문이다. 그래서 흘리지 않는 국소 규칙 둘을 덧입힌다
 * (`SHELF`):
 *
 *   1. 표고 2.5 m 이하의 뭍 칸 둘레 7×7에서 바다가 35% 이상이면 바다 — 두 번만
 *   2. 최고 표고 2.5 m 이하이고 넓이 0.36 km² 미만인 뭍 덩어리(4연결)는 바다
 *
 * 1은 가는 고리를 먹고, 넓은 저지대(간척지)는 가장자리 몇 칸만 깎는다 — 흘리지 않으므로
 * 안쪽으로 번지지 않는다(고흥 팩 실측: 활주로 반경 2.5 km 안에서 바뀐 칸 0). 2는 1이 남긴
 * 낮은 토막을 먹는다. 높은 땅에 붙은 저지대는 덩어리의 최고 표고가 높아 2에 걸리지 않는다.
 *
 * **넓은 티어가 좁은 티어에 주는 시드는 흘린 결과만이다.** 흡수한 칸까지 시드로 주면 간척지
 * 가장자리에서 흡수된 0 칸이 좁은 티어의 흘리기를 간척지 안쪽 0 그물로 끌고 들어간다.
 */

/** `lib/terrainpack.js`가 파싱한 티어 중 이 모듈이 쓰는 부분. */
export interface MaskTier {
  name: string;
  rows: number;
  cols: number;
  /** 행 0의 N 좌표 [m], 열 0의 E 좌표 [m] */
  n0: number;
  e0: number;
  /** 격자 간격 [m] */
  step: number;
  /** 표고 = offset + raw*scale */
  scale: number;
  offset: number;
  nodata: number;
  raw: Uint16Array;
}

/** 셀 상태. 바다/육지 둘로만 나누면 결측이 어느 한쪽에 조용히 흡수된다. */
export const CELL = { LAND: 0, SEA: 1, MISSING: 2 } as const;
export type Cell = (typeof CELL)[keyof typeof CELL];

export interface TierMask {
  name: string;
  rows: number;
  cols: number;
  cells: Uint8Array;
  /** 바다로 판정된 셀 수(흡수한 해안 턱 포함) — 캡션이 비율을 말한다 */
  seaCells: number;
  /** 그중 해안 턱 흡수로 바다가 된 셀 수 — 머리말 「해안 턱 흡수」 */
  shelfCells: number;
  /** 표고는 해수면인데 육지로 남은 셀 수 (간척지·저지대·양자화 잡음) */
  landAtSeaLevel: number;
  missingCells: number;
}

/** 해수면에 해당하는 raw 값. 양자화 격자에 해수면이 정확히 없으면 null. */
export function seaLevelRaw(tier: Pick<MaskTier, "scale" | "offset">): number | null {
  if (!(tier.scale > 0)) return null;
  const v = (0 - tier.offset) / tier.scale;
  const r = Math.round(v);
  return Math.abs(v - r) < 1e-9 && r >= 0 && r <= 0xffff ? r : null;
}

function atSeaLevel(tier: MaskTier, i: number, seaRaw: number | null): boolean {
  const v = tier.raw[i]!;
  if (v === tier.nodata) return false;
  if (seaRaw !== null) return v === seaRaw;
  // 양자화가 안 떨어지는 팩 — 반 눈금 안이면 해수면으로 본다
  return Math.abs(tier.offset + v * tier.scale) < tier.scale * 0.5;
}

/** 티어의 격자 인덱스 → NED [m] (셀 중심). */
export function cellToNed(tier: Pick<MaskTier, "n0" | "e0" | "step">, r: number, c: number): [number, number] {
  return [tier.n0 + r * tier.step, tier.e0 + c * tier.step];
}

/** NED [m] → 격자 인덱스. 범위 밖이면 null. */
export function nedToCell(
  tier: Pick<MaskTier, "n0" | "e0" | "step" | "rows" | "cols">,
  n: number,
  e: number,
): [number, number] | null {
  const r = Math.round((n - tier.n0) / tier.step);
  const c = Math.round((e - tier.e0) / tier.step);
  if (r < 0 || c < 0 || r >= tier.rows || c >= tier.cols) return null;
  return [r, c];
}

/** 티어 하나를 흘린다. `extraSeeds(r, c)`가 참이면 그 셀도 시드다(넓은 티어의 답). */
function floodTier(
  tier: MaskTier,
  extraSeeds: ((r: number, c: number) => boolean) | null,
): TierMask {
  const { rows, cols } = tier;
  const n = rows * cols;
  const cells = new Uint8Array(n); // 기본 LAND
  const seaRaw = seaLevelRaw(tier);

  let missingCells = 0;
  const isSeaLevel = new Uint8Array(n);
  for (let i = 0; i < n; i++) {
    if (tier.raw[i] === tier.nodata) {
      cells[i] = CELL.MISSING;
      missingCells++;
    } else if (atSeaLevel(tier, i, seaRaw)) {
      isSeaLevel[i] = 1;
    }
  }

  // BFS. 셀이 100만 개라 배열 shift(O(n))는 못 쓴다 — Int32Array 링버퍼.
  const queue = new Int32Array(n);
  let head = 0;
  let tail = 0;
  const push = (i: number) => {
    if (isSeaLevel[i] === 1 && cells[i] !== CELL.SEA) {
      cells[i] = CELL.SEA;
      queue[tail++] = i;
    }
  };

  for (let c = 0; c < cols; c++) {
    push(c);
    push((rows - 1) * cols + c);
  }
  for (let r = 0; r < rows; r++) {
    push(r * cols);
    push(r * cols + cols - 1);
  }
  if (extraSeeds) {
    for (let r = 0; r < rows; r++) {
      for (let c = 0; c < cols; c++) {
        if (extraSeeds(r, c)) push(r * cols + c);
      }
    }
  }

  // 열 가드(`c > 0` / `c + 1 < cols`)는 **행 감김**을 막는다 — 없으면 (r, 0)의 왼쪽이
  // (r-1, cols-1)이 되어 격자가 원통처럼 이어진다. 다만 지금 구현에서 이 가드는
  // 방어일 뿐 동작을 바꾸지 않는다: 감김의 목적지가 **언제나 경계 열**이고, 경계는
  // 위에서 전부 시드로 넣었으므로 해수면이면 이미 SEA다(실측 — 가드를 풀어도 현재
  // 팩에서 셀 단위 차이 0). **둘은 그렇게 묶여 있다.** 경계 시드를 좁히는 변경을
  // 한다면 이 가드가 그때부터 진짜로 일한다 — 같이 보아야 한다.
  while (head < tail) {
    const i = queue[head++]!;
    const r = (i / cols) | 0;
    const c = i - r * cols;
    if (r > 0) push(i - cols);
    if (r + 1 < rows) push(i + cols);
    if (c > 0) push(i - 1);
    if (c + 1 < cols) push(i + 1);
  }

  let seaCells = 0;
  let landAtSeaLevel = 0;
  for (let i = 0; i < n; i++) {
    if (cells[i] === CELL.SEA) seaCells++;
    else if (isSeaLevel[i] === 1) landAtSeaLevel++;
  }
  return { name: tier.name, rows, cols, cells, seaCells, landAtSeaLevel, missingCells, shelfCells: 0 };
}

/** 해안 턱 흡수의 문턱 — 머리말 「해안 턱 흡수」. 표시용 판정이다(원자료를 고치지 않는다). */
export const SHELF = {
  /** 이 표고 [m] 이하의 뭍만 본다 */
  maxElevM: 2.5,
  /** 둘레 창의 반경 [칸] — 7×7 */
  radiusCells: 3,
  /** 창 안 바다 비율이 이 이상이면 바다 */
  seaFrac: 0.35,
  /** 규칙 1을 되풀이하는 횟수 — 넓은 저지대를 이만큼만 깎는다 */
  passes: 2,
  /** 규칙 2의 덩어리 넓이 상한 [m²] */
  maxBlobM2: 360000,
} as const;

/** 흘린 마스크에 해안 턱 흡수를 덧입힌 **새 마스크**. 입력은 건드리지 않는다(시드로 계속 쓴다). */
function absorbShelves(tier: MaskTier, flooded: TierMask): TierMask {
  const { rows, cols } = tier;
  const n = rows * cols;
  const cells = flooded.cells.slice();
  const elev = new Float32Array(n);
  for (let i = 0; i < n; i++) {
    const v = tier.raw[i]!;
    elev[i] = v === tier.nodata ? Number.NaN : tier.offset + v * tier.scale;
  }
  const low = (i: number) => cells[i] === CELL.LAND && elev[i]! <= SHELF.maxElevM;

  // 규칙 1 — 창 안 바다 비율. 합산표로 칸마다 O(1), 갱신은 회차 단위(순서 무관).
  const w = cols + 1;
  const sat = new Int32Array((rows + 1) * w);
  const R = SHELF.radiusCells;
  for (let pass = 0; pass < SHELF.passes; pass++) {
    for (let r = 0; r < rows; r++) {
      let rowSum = 0;
      for (let c = 0; c < cols; c++) {
        rowSum += cells[r * cols + c] === CELL.SEA ? 1 : 0;
        sat[(r + 1) * w + c + 1] = sat[r * w + c + 1]! + rowSum;
      }
    }
    const flip: number[] = [];
    for (let r = 0; r < rows; r++) {
      const r0 = Math.max(r - R, 0);
      const r1 = Math.min(r + R, rows - 1) + 1;
      for (let c = 0; c < cols; c++) {
        const i = r * cols + c;
        if (!low(i)) continue;
        const c0 = Math.max(c - R, 0);
        const c1 = Math.min(c + R, cols - 1) + 1;
        const sea = sat[r1 * w + c1]! - sat[r0 * w + c1]! - sat[r1 * w + c0]! + sat[r0 * w + c0]!;
        if (sea >= SHELF.seaFrac * (r1 - r0) * (c1 - c0)) flip.push(i);
      }
    }
    if (flip.length === 0) break;
    for (const i of flip) cells[i] = CELL.SEA;
  }

  // 규칙 2 — 작은 낮은 덩어리. 4연결 뭍 성분마다 넓이와 최고 표고를 잰다.
  const maxCells = SHELF.maxBlobM2 / (tier.step * tier.step);
  const seen = new Uint8Array(n);
  const stack = new Int32Array(n);
  const members: number[] = [];
  for (let s = 0; s < n; s++) {
    if (seen[s] || cells[s] !== CELL.LAND) continue;
    let top = 0;
    let peak = -Infinity;
    members.length = 0;
    stack[top++] = s;
    seen[s] = 1;
    while (top > 0) {
      const i = stack[--top]!;
      members.push(i);
      if (elev[i]! > peak) peak = elev[i]!;
      const r = (i / cols) | 0;
      const c = i - r * cols;
      for (const j of [r > 0 ? i - cols : -1, r + 1 < rows ? i + cols : -1,
        c > 0 ? i - 1 : -1, c + 1 < cols ? i + 1 : -1]) {
        if (j >= 0 && !seen[j] && cells[j] === CELL.LAND) { seen[j] = 1; stack[top++] = j; }
      }
    }
    if (members.length < maxCells && peak <= SHELF.maxElevM) {
      for (const i of members) cells[i] = CELL.SEA;
    }
  }

  let seaCells = 0;
  let landAtSeaLevel = 0;
  const seaRaw = seaLevelRaw(tier);
  for (let i = 0; i < n; i++) {
    if (cells[i] === CELL.SEA) seaCells++;
    else if (cells[i] === CELL.LAND && atSeaLevel(tier, i, seaRaw)) landAtSeaLevel++;
  }
  return {
    ...flooded, cells, seaCells, landAtSeaLevel, shelfCells: seaCells - flooded.seaCells,
  };
}

/** 티어가 덮는 한 변 [m] — 넓은 것부터 흘리려고 정렬에 쓴다. */
function extentOf(t: MaskTier): number {
  return Math.max(t.rows * t.step, t.cols * t.step);
}

/** 전 티어의 해수면 마스크. **넓은 티어부터 흘려** 좁은 티어의 시드로 넘긴다. */
export function buildSeaMasks(tiers: MaskTier[]): Map<string, TierMask> {
  const order = [...tiers].sort((a, b) => extentOf(b) - extentOf(a));
  const out = new Map<string, TierMask>();
  const done: { tier: MaskTier; mask: TierMask }[] = [];

  for (const tier of order) {
    const seeds = done.length === 0
      ? null
      : (r: number, c: number) => {
        const [n, e] = cellToNed(tier, r, c);
        for (const prev of done) {
          const idx = nedToCell(prev.tier, n, e);
          if (idx && prev.mask.cells[idx[0] * prev.mask.cols + idx[1]] === CELL.SEA) return true;
        }
        return false;
      };
    const mask = floodTier(tier, seeds);
    out.set(tier.name, mask);
    done.push({ tier, mask });
  }
  // 흡수는 **전부 흘린 뒤에** 티어마다 따로 — 머리말 「해안 턱 흡수」 끝 문단
  for (const { tier, mask } of done) out.set(tier.name, absorbShelves(tier, mask));
  return out;
}

/** 이 셀을 지형 삼각형으로 그릴 것인가 — 바다도 결측도 아닐 때만. */
export function isLand(mask: TierMask, r: number, c: number): boolean {
  if (r < 0 || c < 0 || r >= mask.rows || c >= mask.cols) return false;
  return mask.cells[r * mask.cols + c] === CELL.LAND;
}

/** 캡션이 쓸 요약 — 화면이 "얼마나 바다인지"를 수치로 말할 수 있게. */
export function maskSummary(mask: TierMask): { seaFrac: number; landAtSeaLevelFrac: number } {
  const n = mask.rows * mask.cols;
  return {
    seaFrac: n > 0 ? mask.seaCells / n : 0,
    landAtSeaLevelFrac: n > 0 ? mask.landAtSeaLevel / n : 0,
  };
}
