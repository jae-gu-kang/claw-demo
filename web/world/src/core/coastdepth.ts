/** 해안 물속 이음 — 바다 쪽 첫 몇 칸에 **표시용 수심**을 준다 (렌더러 무관).
 *
 * ## 왜 필요한가 — 섬 둘레의 톱니
 *
 * 지형 팩의 바다는 전부 정확히 0 m다(원자료가 수심을 거의 안 싣고, 굽는 스크립트가 해수면에서 자른다).
 * 그러면 물가선, 곧 지형 면이 해면(y = 0)과 만나는 선이 **바다 표본 꼭짓점을 그대로 지나간다** — 땅
 * 꼭짓점에서 바다 꼭짓점으로 내려오는 삼각형마다 끝이 해면에 닿아, 격자에 비스듬한 해안은 삼각형
 * 이빨이 줄지어 선 톱니가 된다. 90 m 외곽 격자의 섬에서 특히 눈에 띄었다(사용자 지적).
 *
 * 바다 쪽 표본을 물속으로 내리면 땅 꼭짓점(H)과 바다 꼭짓점(−D) 사이 변에서 높이가 0이 되는 자리가
 * 변 **안쪽**(땅에서 H/(H+D))으로 들어온다. 물가선이 격자 꼭짓점이 아니라 높이를 따라 그어지고,
 * 낮은 땅은 물이 깊숙이 들어오고 가파른 땅은 물가에서 바로 솟는다.
 *
 * ## 얼마나 내리나 — 표시 값이다
 *
 * 땅에 맞닿은 첫 고리(8이웃에 땅이 있는 바다 표본)는 맞닿은 땅 높이 평균의 0.8배(1~15 m)만큼 내린다 —
 * 물가선이 땅·바다 표본 사이 가운데쯤에 온다(해수면 판정이 그 사이 어딘가라고만 알려 주므로 가운데가
 * 가장 덜 지어내는 자리다). 둘째·셋째 고리는 앞 고리의 1.6배씩 깊어져(최대 30 m) 3차 보간(core/refine.ts)이
 * 물속에 둔덕을 만들지 않게 한다. 그 바깥 바다는 손대지 않는다 — 모두 바다인 칸은 그리지 않으므로 안 보인다.
 *
 * **실제 수심이 아니다.** 해면 아래는 물이 가리고(바다 셰이더), 지면 높이 판독은 원자료 격자를 쓴다
 * (SceneController.groundElevationAt) — 이 값은 그림에만 들어간다. 캡션이 그렇게 말한다(scene/terrain.ts).
 */

import { CELL } from "./seamask.ts";

export const COAST_DEPTH = {
  /** 첫 고리 수심 = 맞닿은 땅 높이 평균 × 이 값 */
  firstRingGain: 0.8,
  minM: 1,
  maxFirstM: 15,
  /** 고리마다 깊어지는 배율과 상한 */
  ringGrowth: 1.6,
  maxM: 30,
  /** 내리는 고리 수 — 3차 보간의 지지 범위(4×4)가 닿는 데까지 */
  rings: 3,
} as const;

/** 표고 격자(행 우선, 결측 NaN)와 해수면 판정 → 바다 쪽 고리에 표시용 수심을 넣은 **새 격자**. */
export function coastalDepths(
  elev: ArrayLike<number>, rows: number, cols: number, cells: ArrayLike<number>,
): Float32Array {
  const n = rows * cols;
  const out = Float32Array.from(elev as ArrayLike<number>);
  const ring = new Int8Array(n); // 0 = 아직, k = k번째 고리
  let frontier: number[] = [];

  // 첫 고리 — 8이웃에 땅이 있는 바다 표본
  for (let r = 0; r < rows; r++) {
    for (let c = 0; c < cols; c++) {
      const i = r * cols + c;
      if (cells[i] !== CELL.SEA) continue;
      let sum = 0;
      let k = 0;
      for (let dr = -1; dr <= 1; dr++) {
        for (let dc = -1; dc <= 1; dc++) {
          if (!dr && !dc) continue;
          const rr = r + dr;
          const cc = c + dc;
          if (rr < 0 || cc < 0 || rr >= rows || cc >= cols) continue;
          const j = rr * cols + cc;
          if (cells[j] !== CELL.LAND) continue;
          const z = elev[j]!;
          if (!Number.isFinite(z)) continue;
          sum += Math.max(z, 0);
          k++;
        }
      }
      if (k === 0) continue;
      const d = Math.min(Math.max(COAST_DEPTH.firstRingGain * (sum / k), COAST_DEPTH.minM), COAST_DEPTH.maxFirstM);
      out[i] = -d;
      ring[i] = 1;
      frontier.push(i);
    }
  }

  // 다음 고리들 — 앞 고리 이웃의 수심 평균 × 배율. 회차 단위로 정하므로 순서와 무관하다.
  for (let k = 2; k <= COAST_DEPTH.rings && frontier.length > 0; k++) {
    const next = new Map<number, { sum: number; n: number }>();
    for (const i of frontier) {
      const r = (i / cols) | 0;
      const c = i - r * cols;
      for (let dr = -1; dr <= 1; dr++) {
        for (let dc = -1; dc <= 1; dc++) {
          if (!dr && !dc) continue;
          const rr = r + dr;
          const cc = c + dc;
          if (rr < 0 || cc < 0 || rr >= rows || cc >= cols) continue;
          const j = rr * cols + cc;
          if (cells[j] !== CELL.SEA || ring[j] !== 0) continue;
          const acc = next.get(j) ?? { sum: 0, n: 0 };
          acc.sum += -out[i]!;
          acc.n++;
          next.set(j, acc);
        }
      }
    }
    frontier = [];
    for (const [j, acc] of next) {
      out[j] = -Math.min(COAST_DEPTH.ringGrowth * (acc.sum / acc.n), COAST_DEPTH.maxM);
      ring[j] = k;
      frontier.push(j);
    }
  }
  return out;
}
