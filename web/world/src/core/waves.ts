/** 해면 파동과 경사 통계 — **재미있는 계산은 렌더러 밖에.**
 *
 * 셰이더는 여기서 나온 수를 받아 더하기만 한다. 그래야 분산관계·스펙트럼·경사분산이
 * 테스트에 걸린다(`docs/fcs-context-02-implementation.md` §4가 three 예외를 허용하며
 * 건 조건이 그것이다).
 *
 * ## 이것은 시뮬 입력이 아니다
 *
 * 풍속은 **표시 값**이다. 비행동역학은 이 값을 모른다 — `engine/`의 바람 모델과 무관하고,
 * 궤적·자세·타면은 여기를 지나가지 않는다. 캡션이 그렇게 말한다(`WAVE_NOTES`).
 *
 * ## 모델
 *
 * 심해 분산관계 `ω² = g·k`, `k = 2π/L`. 유의파고는 피어슨-모스코비츠
 * `H_s = 0.21 U² / g`, 첨두 파장은 `L_p = 2π g / ω_p²`, `ω_p = 0.877 g / U`.
 * 두 식이 풍속 하나에서 **파고와 파장을 함께** 낸다 — 그래서 바람을 올리면 파도가
 * 높아지는 동시에 길어진다. 임의의 상수를 손으로 고르면 그 둘이 따로 논다.
 *
 * 성분 다섯은 첨두 파장 둘레에 흩고(§gerstnerSet), 진폭은
 * `H_s = 4√m₀`, `m₀ = Σ A²/2` 로 맞춘다.
 */

/** 표준중력 [m/s²] — `engine/claw/env/`와 같은 값. */
export const G = 9.80665;

/** 게르스트너 성분 하나. 셰이더가 그대로 읽는다. */
export interface GerstnerWave {
  /** 진행 방향 (수평면 단위벡터, 렌더 좌표 x·z) */
  dir: [number, number];
  /** 파장 [m] */
  length: number;
  /** 진폭 [m] — 파고의 절반 */
  amplitude: number;
  /** 파수 k = 2π/L [rad/m] */
  k: number;
  /** 각주파수 ω = √(g k) [rad/s] */
  omega: number;
  /** 가파름 계수 Q — 마루가 뾰족해지는 정도. `Q·k·A ≤ 1`이라야 고리가 안 생긴다. */
  q: number;
}

/** 유의파고 [m] — 피어슨-모스코비츠. `H_s = 0.21 U²/g`. */
export function significantWaveHeight(windSpeed: number): number {
  const u = Math.max(windSpeed, 0);
  return (0.21 * u * u) / G;
}

/** 첨두 파장 [m] — PM 첨두 주파수 `ω_p = 0.877 g/U`에서.
 *
 * 풍속이 0에 가까우면 파장도 0으로 가는데, 그러면 파수가 발산한다. 하한을 둔다. */
export function peakWavelength(windSpeed: number): number {
  const u = Math.max(windSpeed, 0.5);
  const omegaP = (0.877 * G) / u;
  return (2 * Math.PI * G) / (omegaP * omegaP);
}

/** 콕스-먼크 경사분산 σ² (양축 합) — 윤슬의 폭을 정하는 한 줄.
 *
 * `σ² = 0.003 + 0.00512 U` (Cox & Munk 1954, 청정 해면). 마이크로패싯 거칠기로 옮길
 * 때는 베크만 분포의 경사분산이 곧 α²이므로 **α = σ**다.
 *
 * **주의 — 이중 계산이 있다.** σ²는 모세관파까지 포함한 *전체* 경사분산인데, 게르스트너
 * 성분이 이미 그중 큰 파장 쪽을 기하로 들고 있다. 엄밀하려면 해상된 몫을 빼야 하지만,
 * 화면의 격자가 그 몫을 제대로 풀지 못하므로(먼바다 한 삼각형이 수백 m다) 전체를 쓰는
 * 편이 눈에 맞는다. 표시용 선택이고 캡션이 밝힌다. */
export function coxMunkSlopeVariance(windSpeed: number): number {
  return 0.003 + 0.00512 * Math.max(windSpeed, 0);
}

/** 성분의 상대 파장(첨두 대비)과 진폭 가중치. 다섯 개로 너울·중파를 함께 덮는다. */
const COMPONENTS: readonly { lengthRatio: number; weight: number; spreadDeg: number }[] = [
  { lengthRatio: 1.9, weight: 1.00, spreadDeg: 0 },    // 너울 — 바람 방향
  { lengthRatio: 1.15, weight: 0.78, spreadDeg: -22 },
  { lengthRatio: 0.62, weight: 0.52, spreadDeg: 31 },
  { lengthRatio: 0.31, weight: 0.34, spreadDeg: -47 },
  { lengthRatio: 0.15, weight: 0.21, spreadDeg: 58 },  // 중파 — 방향이 가장 벌어진다
];

/** 셰이더가 받는 성분 수. 유니폼 배열 길이와 **같아야 한다**(`shaders/ocean.ts`). */
export const WAVE_COUNT = COMPONENTS.length;

/** 풍속·풍향에서 게르스트너 성분 다섯을 만든다.
 *
 * @param windSpeed [m/s]
 * @param windDirRad 바람이 **가는** 방향 [rad] — 렌더 좌표 x·z 평면에서 +x 기준 반시계
 * @param steepness 0~1. 1이면 마루가 첨점에 닿는다(`Q·k·A = 1`). 1을 넘으면 고리가 생긴다.
 */
export function gerstnerSet(
  windSpeed: number, windDirRad: number, steepness = 0.65,
): GerstnerWave[] {
  const hs = significantWaveHeight(windSpeed);
  const lp = peakWavelength(windSpeed);

  // 진폭을 H_s에 맞춘다: H_s = 4√m₀, m₀ = Σ A²/2 → Σ A² = H_s²/8.
  const wsum = COMPONENTS.reduce((s, c) => s + c.weight * c.weight, 0);
  const scale = wsum > 0 ? Math.sqrt((hs * hs) / 8 / wsum) : 0;
  const s = Math.min(Math.max(steepness, 0), 1);

  return COMPONENTS.map((c) => {
    const length = Math.max(lp * c.lengthRatio, 0.5);
    const k = (2 * Math.PI) / length;
    const amplitude = scale * c.weight;
    const a = windDirRad + (c.spreadDeg * Math.PI) / 180;
    // **고리를 못 만들게 나눠 둔다.** 성분마다 Q·k·A ≤ 1/N이면 합쳐도 1을 안 넘는다.
    const q = amplitude > 0 ? s / (k * amplitude * WAVE_COUNT) : 0;
    return {
      dir: [Math.cos(a), Math.sin(a)],
      length,
      amplitude,
      k,
      omega: Math.sqrt(G * k),
      q,
    };
  });
}

/** 캡션 원장 — 해면은 전부 표시용이다. */
export const WAVE_NOTES = {
  displayOnly:
    "해상 상태(풍속·파고·파향)는 표시 값이며 시뮬 입력이 아닙니다 — "
    + "비행동역학은 이 값을 모릅니다.",
  model:
    "파면은 게르스트너 성분 5개(심해 분산관계 ω²=gk)이고 파고는 피어슨-모스코비츠 "
    + "H_s=0.21U²/g입니다. 윤슬 폭은 콕스-먼크 경사분산 σ²=0.003+0.00512U에서 나옵니다.",
} as const;
