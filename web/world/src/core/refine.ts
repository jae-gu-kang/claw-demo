/** 격자 세분 — 성긴 표고 격자를 그릴 때만 3차 보간으로 촘촘히 한다 (렌더러 무관).
 *
 * ## 왜 필요한가 — 외곽의 피라미드 언덕
 *
 * 90 m 외곽 격자에서 폭 150~200 m의 실제 작은 언덕은 표본 한두 개로 잡힌다. 그 표본을 직선으로 이으면
 * 꼭짓점 하나에 면 여덟 장이 모인 **피라미드**가 되고, 능선도 곧은 칼날이 된다(사용자 지적 「외곽 90 m
 * 언덕」). 표본 사이를 캣멀-롬 3차 보간으로 채워 2배 촘촘한 격자(45 m)를 만들면 꼭대기가 둥글어진다.
 *
 * ## 넘침을 자른다
 *
 * 캣멀-롬은 표본을 그대로 지나가지만 급한 계단 옆에서 표본 범위를 살짝 넘는다(최대 계단의 약 7%).
 * 넘친 값은 없는 둔덕·웅덩이다 — 평지 옆 산자락에 고랑이 파이고, 해안에서는 땅이 물 밖으로 솟는다.
 * 그래서 새 값을 **그 칸을 이루는 원래 표본(2개 또는 4개)의 최소~최대로 자른다.** 꼭대기는 원래 표본
 * 높이를 넘지 않고, 칸 안에서만 둥글어진다.
 *
 * ## 결측
 *
 * 지지 범위(4×4)에 결측이 있으면 그 칸 꼭짓점만으로 선형 보간하고, 꼭짓점에도 결측이 있으면 결측이다 —
 * terrainpack.js가 구멍을 구멍으로 두는 규약 그대로다.
 *
 * **표시 전용이다.** 지면 높이 판독·게임 웨이포인트 고도는 원자료 격자를 쓴다.
 */

/** 이 간격 [m] 이상인 격자만 세분한다 — 30 m 촘촘한 장은 원자료 해상도와 같아 세분할 것이 없다. */
export const REFINE_MIN_STEP_M = 60;

/** t = 0.5의 캣멀-롬 가중치 */
const W = [-1 / 16, 9 / 16, 9 / 16, -1 / 16] as const;

export interface RefinedGrid {
  elev: Float32Array;
  rows: number;
  cols: number;
}

/** rows×cols 격자(행 우선, 결측 NaN)를 2배로 세분한다 — 새 격자는 (2·rows−1)×(2·cols−1)이고
 *  짝수 칸은 원래 표본 그대로다. */
export function refineGrid(elev: ArrayLike<number>, rows: number, cols: number): RefinedGrid {
  const R = 2 * rows - 1;
  const C = 2 * cols - 1;
  const out = new Float32Array(R * C);
  // 격자 밖 지지 표본은 **선형 외삽**한다(축마다) — 끝값을 되풀이하면 가장자리에서 직선이 직선으로
  // 재현되지 않는다(경사의 첫 중간점이 4.4가 됐다, 시험). 넘침은 아래 자르기가 막는다.
  const raw = (r: number, c: number): number => elev[r * cols + c]!;
  const atCol = (r: number, c: number): number => {
    if (cols === 1) return raw(r, 0);
    if (c < 0) return 2 * raw(r, 0) - raw(r, 1);
    if (c >= cols) return 2 * raw(r, cols - 1) - raw(r, cols - 2);
    return raw(r, c);
  };
  const at = (r: number, c: number): number => {
    if (rows === 1) return atCol(0, c);
    if (r < 0) return 2 * atCol(0, c) - atCol(1, c);
    if (r >= rows) return 2 * atCol(rows - 1, c) - atCol(rows - 2, c);
    return atCol(r, c);
  };

  for (let i = 0; i < R; i++) {
    const r0 = i >> 1;
    const oddR = (i & 1) === 1;
    for (let j = 0; j < C; j++) {
      const c0 = j >> 1;
      const oddC = (j & 1) === 1;
      const k = i * C + j;
      if (!oddR && !oddC) { out[k] = at(r0, c0); continue; }

      // 이 점을 이루는 원래 표본 — 변 위면 2개, 칸 안이면 4개. 자르기와 결측 물러섬의 기준이다.
      const corners = !oddR ? [at(r0, c0), at(r0, c0 + 1)]
        : !oddC ? [at(r0, c0), at(r0 + 1, c0)]
          : [at(r0, c0), at(r0, c0 + 1), at(r0 + 1, c0), at(r0 + 1, c0 + 1)];
      let lo = Infinity;
      let hi = -Infinity;
      let mean = 0;
      let cornersOk = true;
      for (const v of corners) {
        if (!Number.isFinite(v)) { cornersOk = false; break; }
        lo = Math.min(lo, v); hi = Math.max(hi, v); mean += v / corners.length;
      }
      if (!cornersOk) { out[k] = Number.NaN; continue; }

      let v = 0;
      let ok = true;
      if (!oddR) {
        for (let t = 0; t < 4 && ok; t++) { const s = at(r0, c0 - 1 + t); ok = Number.isFinite(s); v += W[t]! * s; }
      } else if (!oddC) {
        for (let t = 0; t < 4 && ok; t++) { const s = at(r0 - 1 + t, c0); ok = Number.isFinite(s); v += W[t]! * s; }
      } else {
        for (let a = 0; a < 4 && ok; a++) {
          let row = 0;
          for (let b = 0; b < 4 && ok; b++) { const s = at(r0 - 1 + a, c0 - 1 + b); ok = Number.isFinite(s); row += W[b]! * s; }
          v += W[a]! * row;
        }
      }
      out[k] = ok ? Math.min(Math.max(v, lo), hi) : mean; // 지지 범위에 결측이 있으면 선형(꼭짓점 평균)
    }
  }
  return { elev: out, rows: R, cols: C };
}
