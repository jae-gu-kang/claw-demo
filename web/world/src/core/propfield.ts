/** 게임 모드 소품 배치 — 경사·고도 규칙으로 소나무·활엽수·오두막 자리를 정한다.
 *
 * **전부 표시용 장식**이며 실제 식생·건물이 아니다(캡션이 말한다 — 이 저장소의
 * 규약). 배치는 결정론적이다: 같은 지형이면 같은 자리다. `Math.random`을 쓰면
 * 게임 모드를 켤 때마다 숲이 통째로 이사하고, 스크린샷 비교·버그 재현이 불가능해진다.
 *
 * ## 왜 표본 콜백인가
 *
 * 지형 팩의 격자 내부 구조(티어·스트라이드·결측)를 여기서 다시 알면 `terrainpack`과
 * 두 벌이 된다. 표고는 `(n, e) → 표고 | null` 하나로 받는다 — null(격자 밖·결측·
 * 바다 구멍)이면 그 자리에 아무것도 안 놓는다.
 */

export interface PropPlacement {
  /** NED 수평 위치 [m] */
  n: number;
  e: number;
  /** 지면 표고 [m] — 밑동을 여기에 앉힌다 */
  elev: number;
  /** 크기 배율 (1 안팎) */
  scale: number;
  /** 요 회전 [rad] */
  rot: number;
  /** 색 변주 0‥1 — 밝기 지터용 */
  tint: number;
}

export interface PropField {
  pines: PropPlacement[];
  leaves: PropPlacement[];
  cabins: PropPlacement[];
}

/** 배치 규칙 상수 — 게임 감각으로 고른 표시 값.
 *  originClear: 원점(이륙점·발사장) 둘레는 비운다 — 활주로·발사관 위에 나무가
 *  서면 화면이 지형지물을 거짓말한다. */
export const PROPS = {
  gridStep: 95,        // [m] 후보 격자 — 성긴 격자가 곧 개수 상한이다
  originClear: 1200,   // [m]
  seaLevel: 2.5,       // [m] 이하이면 물가/간척지로 보고 비운다
  pineSlopeMax: 0.45,  // 무차원 경사(수평거리당 표고차)
  leafSlopeMax: 0.22,
  cabinSlopeMax: 0.06,
  maxPines: 4200,
  maxLeaves: 1600,
  maxCabins: 42,
} as const;

/** 결정론 해시 → 0‥1. 정수 격자 좌표와 씨앗에서 나온다. */
export function hash2(ix: number, iy: number, seed: number): number {
  let h = (ix * 374761393 + iy * 668265263 + seed * 2246822519) | 0;
  h = Math.imul(h ^ (h >>> 13), 1274126177);
  h ^= h >>> 16;
  return (h >>> 0) / 4294967296;
}

export type ElevSample = (n: number, e: number) => number | null;

/** 경사 추정 — 4 이웃 유한차분. 이웃이 결측이면 급경사로 본다(놓지 않는 쪽이 안전 —
 *  결측 가장자리에 나무를 세우면 구멍 위에 뜬다). */
function slopeAt(sample: ElevSample, n: number, e: number, z0: number, step: number): number {
  const zn = sample(n + step, e);
  const zs = sample(n - step, e);
  const ze = sample(n, e + step);
  const zw = sample(n, e - step);
  if (zn === null || zs === null || ze === null || zw === null) return Infinity;
  return Math.hypot((zn - zs) / (2 * step), (ze - zw) / (2 * step));
}

/** 소품 자리를 정한다.
 * @param rect 배치 범위 (NED) — 보통 core 티어 사각형. 바깥 티어(90 m 격자)까지
 *   깔면 개수가 상한을 눌러 정작 가까운 숲이 성기게 된다.
 * @param relief 램프 정규화 기준 [m] — 수목한계(relief의 0.72)를 램프의 설선과
 *   같은 기준으로 잰다. 절대 고도로 두면 낮은 지형에서 수목한계가 안 나온다. */
export function placeProps(
  sample: ElevSample,
  rect: { n0: number; e0: number; n1: number; e1: number },
  relief: number,
  seed = 1,
): PropField {
  const out: PropField = { pines: [], leaves: [], cabins: [] };
  const step = PROPS.gridStep;
  const treeLine = relief * 0.72;
  const i0 = Math.ceil(rect.n0 / step);
  const i1 = Math.floor(rect.n1 / step);
  const j0 = Math.ceil(rect.e0 / step);
  const j1 = Math.floor(rect.e1 / step);

  for (let i = i0; i <= i1; i++) {
    for (let j = j0; j <= j1; j++) {
      // 격자 + 지터 — 격자 그대로면 숲이 모눈으로 읽힌다.
      const jn = (hash2(i, j, seed) - 0.5) * step * 0.9;
      const je = (hash2(i, j, seed + 1) - 0.5) * step * 0.9;
      const n = i * step + jn;
      const e = j * step + je;
      if (Math.hypot(n, e) < PROPS.originClear) continue;

      const z = sample(n, e);
      if (z === null || z <= PROPS.seaLevel || z > treeLine) continue;
      const slope = slopeAt(sample, n, e, z, step);

      // 군집 — 300 m 규모 해시 2옥타브. 문턱을 넘는 곳만 숲이라 얼룩이 생긴다.
      const ci = Math.floor(n / 300);
      const cj = Math.floor(e / 300);
      const cluster = 0.6 * hash2(ci, cj, seed + 2) + 0.4 * hash2(i >> 1, j >> 1, seed + 3);
      const r = hash2(i, j, seed + 4);

      const base = {
        n, e, elev: z,
        scale: 0.75 + 0.5 * hash2(i, j, seed + 5),
        rot: hash2(i, j, seed + 6) * Math.PI * 2,
        tint: hash2(i, j, seed + 7),
      };
      if (slope < PROPS.cabinSlopeMax && z < 130 && r > 0.985
          && out.cabins.length < PROPS.maxCabins) {
        out.cabins.push(base);
      } else if (slope < PROPS.leafSlopeMax && z < treeLine * 0.45 && cluster > 0.55
          && r > 0.45 && out.leaves.length < PROPS.maxLeaves) {
        out.leaves.push(base);
      } else if (slope < PROPS.pineSlopeMax && cluster > 0.42 && r > 0.35
          && out.pines.length < PROPS.maxPines) {
        out.pines.push(base);
      }
    }
  }
  return out;
}
