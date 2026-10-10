/** 지형 음영 보조량 — 표고 격자에서 **하늘 열림(AO)**과 **볼록도**를 낸다 (렌더러 무관).
 *
 * ## 왜 필요한가
 *
 * 30 m 격자 지형에 태양 하나와 반구광만 비추면 골짜기와 능선이 같은 밝기의 그늘을 받는다 —
 * 반구광은 법선만 보고 주변 산이 하늘을 가리는지는 모른다. 그래서 와이드샷의 산이 찰흙
 * 덩어리처럼 평평하게 읽혔다. 실제 항공사진에서 깊이를 만드는 것은 직사광의 명암보다
 * **골이 하늘을 덜 보는 것**이다.
 *
 * ## 무엇을 재나 — 여러 반경의 상대 표고
 *
 * 반경 R 창의 평균보다 얼마나 낮은가(δ = z − 평균)를 세 반경(60·180·540 m)에서 잰다.
 * 낮으면 그 반경 둘레가 하늘을 가린다고 보고, 가림각의 사인 `−δ / √(δ² + R²)`을 섞어
 * 열림을 깎는다. 지평 탐색(방향마다 광선을 쏘는 HBAO)이 정답에 가깝지만 정점 백만 개에
 * 방향·걸음을 곱하면 메인 스레드에서 초 단위다 — 이 근사는 합산표(SAT)로 반경마다 O(N)이라
 * 수십 ms에 끝난다. 그래서 **표시용 근사**이고, 캡션이 그렇게 말한다(scene/terrain.ts).
 *
 * 볼록도는 180 m 반경의 δ를 25 m로 나눠 −1~1로 자른 것이다 — 셰이더의 지표 피복 판정이
 * 쓴다(볼록한 능선에 암반, 오목한 골 바닥에 논).
 *
 * ## 결측
 *
 * 결측 표고(NaN)는 0(해수면)으로 본다. 결측 칸은 어차피 삼각형이 없어 그려지지 않고,
 * 이웃 칸의 열림이 그만큼 살짝 밝아질 뿐이다 — 지어낸 능선을 세우지 않는 쪽이다.
 */

/** 열림을 재는 반경 [m]과 그 가중치 — 합이 1이다. */
export const AO_SCALES: readonly { radiusM: number; weight: number }[] = [
  { radiusM: 60, weight: 0.3 },
  { radiusM: 180, weight: 0.35 },
  { radiusM: 540, weight: 0.35 },
];
/** 가림각 사인의 가중합을 열림으로 옮기는 배율과 바닥 — 표시 값이다.
 *
 * 물리 기준점: 벽이 34°인 긴 V자 골 바닥의 하늘 보임(코사인 가중)은 cos 34° ≈ 0.83이고,
 * 사방이 막힌 분지면 cos² ≈ 0.69다. 이 근사는 그 골에서 가림 사인을 0.40으로 재므로
 * 배율 0.75면 0.70 — 두 기준 사이, 분지 쪽으로 조금 과장된 값이다. 처음 1.6으로 두었더니
 * 같은 골이 바닥값까지 떨어져(0.35) 산의 그늘이 먹물처럼 고였다. */
export const AO_GAIN = 0.75;
export const AO_FLOOR = 0.45;
/** 볼록도 정규화 [m] — 180 m 반경에서 이만큼 솟으면 +1. */
export const CONVEX_NORM_M = 25;

export interface TerrainShade {
  /** 하늘 열림 0~1 (1 = 막힘 없음). */
  ao: Float32Array;
  /** 볼록도 −1~1 (능선 +, 골 −). */
  convex: Float32Array;
}

/** 합산표 — (rows+1)×(cols+1), 결측은 0. */
function summedArea(heights: ArrayLike<number>, rows: number, cols: number): Float64Array {
  const w = cols + 1;
  const sat = new Float64Array((rows + 1) * w);
  for (let r = 0; r < rows; r++) {
    let rowSum = 0;
    for (let c = 0; c < cols; c++) {
      const z = heights[r * cols + c]!;
      rowSum += Number.isFinite(z) ? z : 0;
      sat[(r + 1) * w + c + 1] = sat[r * w + c + 1]! + rowSum;
    }
  }
  return sat;
}

/** 칸 (r, c) 둘레 ±s 창의 평균 — 격자 밖은 잘라 낸다(가장자리에서 창이 작아진다). */
function boxMean(sat: Float64Array, rows: number, cols: number, r: number, c: number, s: number): number {
  const r0 = Math.max(r - s, 0);
  const c0 = Math.max(c - s, 0);
  const r1 = Math.min(r + s, rows - 1) + 1;
  const c1 = Math.min(c + s, cols - 1) + 1;
  const w = cols + 1;
  const sum = sat[r1 * w + c1]! - sat[r0 * w + c1]! - sat[r1 * w + c0]! + sat[r0 * w + c0]!;
  return sum / ((r1 - r0) * (c1 - c0));
}

/** 표고 격자(행 우선, rows×cols, 간격 stepM) → 칸마다 열림·볼록도. */
export function terrainShade(
  heights: ArrayLike<number>, rows: number, cols: number, stepM: number,
): TerrainShade {
  const n = rows * cols;
  const ao = new Float32Array(n);
  const convex = new Float32Array(n);
  if (n === 0 || !(stepM > 0)) return { ao, convex };
  const sat = summedArea(heights, rows, cols);
  const radii = AO_SCALES.map((k) => Math.max(1, Math.round(k.radiusM / stepM)));
  const mid = radii[1]!;
  for (let r = 0; r < rows; r++) {
    for (let c = 0; c < cols; c++) {
      const i = r * cols + c;
      const zi = heights[i]!;
      const z = Number.isFinite(zi) ? zi : 0;
      let occl = 0;
      for (let k = 0; k < radii.length; k++) {
        const s = radii[k]!;
        const delta = z - boxMean(sat, rows, cols, r, c, s);
        if (delta < 0) {
          // 창 안 점들의 평균 거리는 반경의 0.77배쯤(정사각 창) — 가림각의 밑변으로 쓴다
          const R = 0.77 * s * stepM;
          occl += AO_SCALES[k]!.weight * (-delta / Math.hypot(delta, R));
        }
      }
      ao[i] = Math.min(Math.max(1 - AO_GAIN * occl, AO_FLOOR), 1);
      const dMid = z - boxMean(sat, rows, cols, r, c, mid);
      convex[i] = Math.min(Math.max(dMid / CONVEX_NORM_M, -1), 1);
    }
  }
  return { ao, convex };
}
