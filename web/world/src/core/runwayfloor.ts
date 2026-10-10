/** 활주로 바닥 — 활주로와 그 둘레를 **활주로 표고로 편다** (렌더러 무관).
 *
 * ## 왜 필요한가 — 묻히는 기체, 끊기는 흰 선
 *
 * 지형 원자료(30 m 표고 격자)는 고흥 활주로 위에서 0~2.9 m로 출렁인다 — 포장면의 높이가 아니라 이 자료의 수직
 * 오차 수준의 출렁임이다. 시뮬은 땅을 활주로 표고(`meta.runway.elevation`)의 평면으로 계산하므로, 그 위에 원자료를
 * 그대로 그리면 착륙해 멈춘 기체(무게중심 0.5 m)가 1.1 m로 솟은 지면에 묻혀 재생 마지막 4분 동안 사라지고, 활주로
 * 표고에 그은 흰 선은 솟은 자리마다 땅에 가려 토막으로 보였다(사용자 지적).
 *
 * ## 어디까지 펴나 — 표시 값이다
 *
 * 축 양옆 75 m, 시단 앞·종단 너머 120 m를 활주로 표고로 평평하게 하고(착륙대의 관례 크기 — ICAO 부속서 14의
 * 정지 구역은 축에서 75 m, 착륙대는 활주로·과주로 끝 너머 60 m이고 고흥 과주로가 61 m다), 그 바깥 90 m(30 m 격자
 * 세 칸)에서 원자료로 부드럽게 돌아간다. 포장면 위 삼각형은 꼭짓점이 **모두** 평평한 구역에 들어야 평평하므로,
 * 포장면 가장자리에서 격자 대각선(30√2 ≈ 42 m)보다 넓게 편다(고흥 반폭 22.5 + 42 < 75, 과주로 61 + 42 < 120 —
 * 시험이 칸마다 확인한다). 가상환경이 칠하는 비행장 풀밭이 이 구역이다(shaders/ground.ts).
 *
 * ## 지형과 맞을 때만 편다
 *
 * 활주로 표고는 시뮬 폼의 시작 고도 칸에서 온다(web/js/lib/simrequest.js). 그 값이 그 자리 원자료 범위에서
 * `FLOOR_FIT_M` 넘게 벗어나면 펴지 않는다 — 12 m를 넣은 런에 12 m 둑을 지어 「지면 +0」이라고 말하게 된다(리뷰
 * 지적). 펴지 않으면 지상의 기체가 그만큼 떠 보이거나 묻혀 보이고, 판독도 원자료 그대로라 어긋남이 화면에 남는다.
 * 정하는 자리는 지형 조립 한 곳이다(scene/terrain.ts `buildTerrain`, 활주로를 덮는 가장 촘촘한 티어).
 *
 * ## 물가는 펴지 않는다
 *
 * 바다 쪽 물속 이음(core/coastdepth.ts)이 내린 표본과 **바다에 맞닿은 땅 표본**은 건드리지 않는다 — 표고 0의
 * 바닥으로 물가 땅을 펴면 꼭짓점이 해수면에 붙어 물가선이 다시 꼭짓점 톱니가 된다(리뷰가 시험 섬에서 확인).
 * 고르는 일은 호출측 몫이다(`floorGrid`·`floorSource`의 `keep`). 고흥은 바다가 활주로에서 3.7 km 밖이다.
 *
 * ## 그림과 판독이 같은 함수를 쓴다
 *
 * 그릴 격자(scene/terrain.ts `renderTier`)와 지면 높이 판독(SceneController `groundElevationAt`)이 `floorElevation`
 * 한 자리를 본다 — 펴진 바닥 위에 선 기체가 「지면 −1」로 읽히면 화면이 자기 말과 어긋난다. 원자료 팩은 바꾸지
 * 않는다(그림 전용 격자에만 들어간다). 캡션이 그렇게 말한다(scene/terrain.ts).
 */

export interface RunwayFloor {
  /** 활주로 축 방위 [rad] — 북에서 동으로 */ heading: number;
  /** 시단(NED 원점)에서 종단까지 [m] */ length: number;
  /** 활주로 표고 [m] — 시뮬이 땅으로 쓰는 높이 */ elevation: number;
}

/** 바닥 표고가 그 자리 원자료 범위에서 벗어나도 되는 폭 [m] — 넘으면 펴지 않는다(머리말 「지형과 맞을 때만」). */
export const FLOOR_FIT_M = 3;

export const RUNWAY_FLOOR = {
  /** 축에서 양옆으로 평평하게 펴는 거리 [m] */
  halfWidthM: 75,
  /** 시단 앞·종단 너머로 펴는 거리 [m] — 과주로 끝에서 다시 착륙대 60 m */
  endM: 120,
  /** 그 바깥에서 원자료로 돌아가는 폭 [m] — 30 m 격자 세 칸 */
  blendM: 90,
} as const;

const num = (v: unknown): number | null =>
  typeof v === "number" && Number.isFinite(v) ? v : null;

/** 결과의 활주로(`meta.runway`) → 바닥. 방위·길이가 없거나 길이가 0 이하면 null(펼 자리를 모른다). 표고가 없으면
 *  0 — 활주로 선(core/runway.ts)과 지형 없는 기준면이 쓰는 것과 같은 값이다. */
export function runwayFloorOf(rw: unknown): RunwayFloor | null {
  const r = (rw ?? null) as { heading?: unknown; length?: unknown; elevation?: unknown } | null;
  const heading = num(r?.heading);
  const length = num(r?.length);
  if (heading === null || length === null || length <= 0) return null;
  return { heading, length, elevation: num(r?.elevation) ?? 0 };
}

/** 두 바닥이 같은가 — 게임 지형 캐시가 묻는다(팩이 같아도 결과의 활주로가 바뀌면 다시 굽는다). */
export function sameFloor(a: RunwayFloor | null, b: RunwayFloor | null): boolean {
  if (a === null || b === null) return a === b;
  return a.heading === b.heading && a.length === b.length && a.elevation === b.elevation;
}

/** (n, e)에서 바닥이 원자료를 덮는 비율 — 펴는 구역 안은 1, 그 바깥 `blendM`에 걸쳐 0으로(smoothstep).
 *  구역에서 잰 거리라 귀퉁이는 둥글게 돌아간다. */
export function floorWeight(f: RunwayFloor, n: number, e: number): number {
  const ca = Math.cos(f.heading);
  const sa = Math.sin(f.heading);
  const along = n * ca + e * sa;
  const across = -n * sa + e * ca;
  const dx = Math.max(-RUNWAY_FLOOR.endM - along, along - f.length - RUNWAY_FLOOR.endM, 0);
  const dy = Math.max(Math.abs(across) - RUNWAY_FLOOR.halfWidthM, 0);
  const d = Math.hypot(dx, dy);
  if (d >= RUNWAY_FLOOR.blendM) return 0;
  const t = d / RUNWAY_FLOOR.blendM;
  return 1 - t * t * (3 - 2 * t);
}

/** 원자료 표고 z → 바닥을 얹은 표고. 펴는 구역 안은 **정확히** 활주로 표고다(z + (표고 − z)는 부동소수에서
 *  표고로 안 떨어질 수 있다). 결측은 결측 그대로 — 없는 땅을 지어내지 않는다. */
export function floorElevation(f: RunwayFloor, n: number, e: number, z: number): number {
  if (!Number.isFinite(z)) return z;
  const w = floorWeight(f, n, e);
  if (w >= 1) return f.elevation;
  return w > 0 ? z + (f.elevation - z) * w : z;
}

/** 원자료 표고 범위 [m] */
export interface FloorSource { min: number; max: number }

export interface FloorResult {
  elev: Float32Array;
  /** 바닥이 손댄 표본 수(가중 > 0) */
  touched: number;
  /** 평평하게 편 표본(가중 1)의 원자료 범위 — `floorSource`와 같다. 그런 표본이 없으면 null */
  source: FloorSource | null;
}

/** 바닥 표고가 원자료 범위에서 `FLOOR_FIT_M` 안인가 — 원자료를 모르면(활주로 자리를 안 덮으면) 거짓. */
export function floorFits(f: RunwayFloor, src: FloorSource | null): boolean {
  return src !== null && f.elevation >= src.min - FLOOR_FIT_M && f.elevation <= src.max + FLOOR_FIT_M;
}

/** 바닥이 닿는 행·열 범위 [r0, r1, c0, c1](이음 포함) — 구역 네 귀퉁이를 NED로 돌려 잰다. 격자 밖이면 비어 있다. */
function floorRange(
  rows: number, cols: number, n0: number, e0: number, step: number, f: RunwayFloor,
): [number, number, number, number] {
  const ca = Math.cos(f.heading);
  const sa = Math.sin(f.heading);
  const reach = RUNWAY_FLOOR.endM + RUNWAY_FLOOR.blendM;
  const side = RUNWAY_FLOOR.halfWidthM + RUNWAY_FLOOR.blendM;
  let nMin = Infinity;
  let nMax = -Infinity;
  let eMin = Infinity;
  let eMax = -Infinity;
  for (const a of [-reach, f.length + reach]) {
    for (const s of [-side, side]) {
      const n = a * ca - s * sa;
      const e = a * sa + s * ca;
      nMin = Math.min(nMin, n); nMax = Math.max(nMax, n);
      eMin = Math.min(eMin, e); eMax = Math.max(eMax, e);
    }
  }
  return [
    Math.max(0, Math.floor((nMin - n0) / step)), Math.min(rows - 1, Math.ceil((nMax - n0) / step)),
    Math.max(0, Math.floor((eMin - e0) / step)), Math.min(cols - 1, Math.ceil((eMax - e0) / step)),
  ];
}

/** 펴는 구역(가중 1) 표본의 원자료 범위 — 결측과 `keep(i)`가 거짓인 표본은 뺀다. 그런 표본이 없으면 null.
 *  격자 꼴은 `floorGrid`와 같다. */
export function floorSource(
  elev: ArrayLike<number>, rows: number, cols: number, n0: number, e0: number, step: number,
  f: RunwayFloor, keep: (i: number) => boolean = () => true,
): FloorSource | null {
  const [r0, r1, c0, c1] = floorRange(rows, cols, n0, e0, step, f);
  let min = Infinity;
  let max = -Infinity;
  for (let r = r0; r <= r1; r++) {
    for (let c = c0; c <= c1; c++) {
      const i = r * cols + c;
      const z = elev[i]!;
      if (!Number.isFinite(z) || !keep(i) || floorWeight(f, n0 + r * step, e0 + c * step) < 1) continue;
      min = Math.min(min, z);
      max = Math.max(max, z);
    }
  }
  return Number.isFinite(min) ? { min, max } : null;
}

/** 표고 격자(행 우선, 결측 NaN — 행 r의 N = n0 + r·step, 열 c의 E = e0 + c·step)에 바닥을 얹은 **새 격자**.
 *  `keep(i)`가 거짓인 표본은 그대로 둔다(호출측이 물가를 지킨다). 바닥이 닿는 행·열만 훑는다. 맞는지(`floorFits`)는
 *  묻지 않는다 — 정하는 것은 호출측이다. */
export function floorGrid(
  elev: ArrayLike<number>, rows: number, cols: number, n0: number, e0: number, step: number,
  f: RunwayFloor, keep: (i: number) => boolean = () => true,
): FloorResult {
  const out = Float32Array.from(elev as ArrayLike<number>);
  const [r0, r1, c0, c1] = floorRange(rows, cols, n0, e0, step, f);
  let touched = 0;
  for (let r = r0; r <= r1; r++) {
    for (let c = c0; c <= c1; c++) {
      const i = r * cols + c;
      const z = out[i]!;
      if (!Number.isFinite(z) || !keep(i)) continue;
      const n = n0 + r * step;
      const e = e0 + c * step;
      if (floorWeight(f, n, e) <= 0) continue;
      touched++;
      out[i] = floorElevation(f, n, e, z);
    }
  }
  return { elev: out, touched, source: floorSource(elev, rows, cols, n0, e0, step, f, keep) };
}
