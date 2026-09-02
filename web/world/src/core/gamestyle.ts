/** 게임 모드 표시 색 — 로우폴리 고도 램프. **표시 전용**이고 실제 지표 피복이 아니다.
 *
 * ## 왜 절대 고도가 아니라 정규화 고도인가
 *
 * 레퍼런스 미감(밝은 갈색 산·초록 들판·설산 정상)은 "그 지역에서 가장 높은 곳이
 * 눈"이라는 상대 규칙이다. 절대 고도로 눈금을 박으면(예: 1,200 m부터 눈) 최고봉이
 * 600 m대인 해안 지형에서는 눈이 영영 안 나오고, 램프의 위 절반이 죽는다. 그래서
 * 팩 헤더의 `elev_max`로 정규화한다 — 지형 팩이 바뀌어도 미감이 유지된다.
 *
 * ## sRGB → 선형
 *
 * 값은 사람이 고르는 공간(sRGB 감각)으로 적고 선형으로 바꿔 넣는다 —
 * `SceneHost.hypsometric`이 겪고 고친 그 함정(선형 정점색을 sRGB로 적으면 화면이
 * 씻긴 듯 밝아진다)과 같은 사유다.
 */

/** 정규화 고도 t(0~1) → sRGB 색. 경계는 겹치지 않는 오름차순 구간이다. */
const STOPS: [number, [number, number, number]][] = [
  [0.00, [0.44, 0.67, 0.31]], // 저지 들판 — 밝은 초록
  [0.14, [0.35, 0.58, 0.27]], // 숲 지대 초록
  [0.32, [0.63, 0.48, 0.29]], // 산허리 — 따뜻한 황갈
  [0.55, [0.48, 0.34, 0.22]], // 능선 갈색
  [0.76, [0.42, 0.32, 0.24]], // 설선 직전의 어두운 바위
  [0.84, [0.90, 0.91, 0.93]], // 눈 — 좁은 구간에서 확 바뀌어야 설선으로 읽힌다
  [1.00, [0.96, 0.96, 0.98]],
];

/** 팩 티어들의 최고 표고 [m] — 램프 정규화 기준. 헤더에 없으면 800으로 물러선다
 *  (내륙 산지의 흔한 스케일 — 0으로 물러서면 전 지형이 눈이 된다). */
export function reliefOf(tiers: readonly { elev_max?: number }[]): number {
  let top = 0;
  for (const t of tiers) {
    if (typeof t.elev_max === "number" && Number.isFinite(t.elev_max)) {
      top = Math.max(top, t.elev_max);
    }
  }
  return top > 10 ? top : 800;
}

/** 표고 → **선형** RGB. `out[i..i+2]`에 써 넣는다 — 정점 루프에서 배열 할당을 피한다. */
export function gameRamp(elev: number, relief: number, out: Float32Array, i: number): void {
  const t = Math.min(Math.max(relief > 0 ? elev / relief : 0, 0), 1);
  let lo = STOPS[0]!;
  let hi = STOPS[STOPS.length - 1]!;
  for (let k = 0; k + 1 < STOPS.length; k++) {
    if (t <= STOPS[k + 1]![0]) { lo = STOPS[k]!; hi = STOPS[k + 1]!; break; }
  }
  const span = hi[0] - lo[0];
  const f = span > 0 ? (t - lo[0]) / span : 0;
  for (let k = 0; k < 3; k++) {
    const srgb = lo[1][k]! + (hi[1][k]! - lo[1][k]!) * f;
    out[i + k] = Math.pow(srgb, 2.2);
  }
}

/** 게임 모드 해면 색 (선형 RGB) — 레퍼런스의 청록. 물리 기본값은 `scene/ocean.ts`가
 *  들고 있고, 여기는 게임 벌만 둔다 — 두 벌이 한 파일에 있으면 하나를 고칠 때
 *  다른 하나를 실수로 만진다. */
export const GAME_SEA = {
  deep: [0.010, 0.078, 0.082] as const,
  shallow: [0.055, 0.300, 0.280] as const,
  scatter: [0.030, 0.190, 0.200] as const,
};
