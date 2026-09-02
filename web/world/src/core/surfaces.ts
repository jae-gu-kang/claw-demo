/** 조종면 각도 — 텔레메트리(de·da·dr·thr)에서 모델 노드가 돌 각을 낸다 (rad, 렌더러 무관).
 *
 * ## 신호는 명령이 아니라 **실제 위치**다
 *
 * `sim/simulator.py`가 작동기를 지난 뒤에 기록한다:
 *
 *     positions = [a.step(sc.elevon[i]) for a in elev_act]   # 실제 타면 위치
 *     de = mean(positions)
 *     da = (positions[0] - positions[2]) / 2
 *     dr = rud_act.step(sc.rudder)
 *
 * 그래서 이 모듈이 내는 각은 지연·rate 한계가 이미 반영된 값이고, 화면이 명령을
 * 그리는 것이 아니라 **기체가 실제로 한 것**을 그린다.
 *
 * ## 재구성은 왜 정확한가
 *
 * 믹서가 좌 2면에 같은 명령, 우 2면에 같은 명령을 준다(`fcl/mixer.py` — 내/외측 1:1
 * 고정 믹싱). 네 작동기가 같은 모델·같은 트림 웜스타트라 좌 둘과 우 둘이 항상 같은
 * 값이고, 따라서
 *
 *     de = (p_L + p_R)/2,  da = (p_L − p_R)/2   →   p_L = de + da,  p_R = de − da
 *
 * 가 **근사가 아니라 항등**이다. 작동기가 면마다 달라지면 그때부터 근사가 된다 —
 * 그 변경이 오면 이 주석이 재검토 조건이다.
 *
 * ## 내측과 외측은 구분되지 않는다 — 화면이 그렇게 말해야 한다
 *
 * 모델(`models/shahed-136/`)에는 엘레본이 **4면 독립**으로 있지만 시뮬은 좌/우 둘만
 * 구분한다. 화면에서 내·외측이 똑같이 움직이는 것은 버그가 아니라 시뮬이 아는 전부다.
 * `SURFACE_NOTES`가 캡션에 그대로 실린다.
 */

import { finite, type Sample } from "./types.ts";

/** 화면이 밝혀야 할 표시 사실 — 캡션 원장. */
export const SURFACE_NOTES = {
  innerOuterShared:
    "엘레본 내측·외측은 같은 각을 씁니다 — 믹서가 1:1 고정이라 시뮬이 둘을 구분하지 않습니다.",
  rudderShared:
    "러더 두 면은 같은 각을 씁니다 — 시뮬의 러더 채널이 하나입니다.",
  propellerDisplay:
    "프로펠러 회전은 좌·우 스로틀 평균에 비례한 표시 값이며, 실제 회전수가 아닙니다.",
  holdOnMissing:
    "조종면 각이 결측인 구간에서는 **마지막 각을 유지**합니다 — 중립으로 되돌리면 "
    + "없는 조종 입력을 그리게 됩니다. 결측이 계속되면 타면이 움직이지 않습니다.",
  skidDisplay:
    "스키드 압축은 표시 근사입니다 — 신호에 수직반력 **합**만 있어 네 점을 같이 누르고, "
    + "그 합에는 감쇠 항(c·δ̇)이 섞여 있어 접지 순간에는 실제보다 깊게 눌립니다.",
} as const;

/** 엘레본 4면 [rad], TE down +. 모델 노드 이름과 1:1. */
export interface ElevonAngles {
  Elevon_In_L: number;
  Elevon_Out_L: number;
  Elevon_In_R: number;
  Elevon_Out_R: number;
}

export interface SurfacePose {
  elevon: ElevonAngles;
  /** 러더 두 면 [rad], TE left + — 시뮬 채널이 하나라 같은 값이 간다. */
  rudder: number;
  /** 한계를 넘어 잘린 면이 있었나 — 캡션이 그 사실을 말할 수 있게. */
  clamped: boolean;
}

/** 타면 위치 한계 [rad] — 결과의 `meta.limits`가 정본. **미상은 null**이고 안 자른다. */
export interface SurfaceLimits {
  elevon_lo?: number | null; elevon_hi?: number | null;
  rudder_lo?: number | null; rudder_hi?: number | null;
}

function clamp(v: number, lo: number | null | undefined, hi: number | null | undefined): [number, boolean] {
  let out = v;
  if (typeof lo === "number" && Number.isFinite(lo) && out < lo) out = lo;
  if (typeof hi === "number" && Number.isFinite(hi) && out > hi) out = hi;
  return [out, out !== v];
}

/** de·da·dr → 여섯 면의 각. 하나라도 결측이면 **null**(0으로 메우지 않는다).
 *
 * 결측을 0으로 메우면 타면이 중립으로 돌아간 **없는 장면**을 그리게 된다.
 */
export function surfacePose(
  de: Sample | undefined,
  da: Sample | undefined,
  dr: Sample | undefined,
  limits: SurfaceLimits = {},
): SurfacePose | null {
  const e = finite(de);
  const a = finite(da);
  const r = finite(dr);
  if (e === null || a === null || r === null) return null;

  const [left, cl] = clamp(e + a, limits.elevon_lo, limits.elevon_hi);
  const [right, cr] = clamp(e - a, limits.elevon_lo, limits.elevon_hi);
  const [rud, cd] = clamp(r, limits.rudder_lo, limits.rudder_hi);

  return {
    elevon: {
      Elevon_In_L: left, Elevon_Out_L: left,
      Elevon_In_R: right, Elevon_Out_R: right,
    },
    rudder: rud,
    clamped: cl || cr || cd,
  };
}

/** 프로펠러 각속도 [rad/s] — **표시 값**이다.
 *
 * 시뮬에 회전수 모델이 없다. 있는 것은 정규화 스로틀 둘뿐이라, 그 평균을 회전속도에
 * 선형으로 태운다. 실제 RPM이 아니고 캡션이 그렇게 말한다(`SURFACE_NOTES`).
 *
 * 스로틀이 하나만 결측이면 남은 쪽을 쓰지 않는다 — 쌍발의 한쪽만 보고 회전을 지어내면
 * 그건 없는 정보다. 둘 다 결측이면 null이고 호출측이 프로펠러를 멈춘 채 둔다.
 */
export function propellerRate(
  thrL: Sample | undefined,
  thrR: Sample | undefined,
  maxRadPerSec = 220,
): number | null {
  const l = finite(thrL);
  const r = finite(thrR);
  if (l === null || r === null) return null;
  const mean = Math.min(Math.max((l + r) / 2, 0), 1);
  return mean * maxRadPerSec;
}

/** 스키드 압축량 [m] — `n_gear`(수직반력 합, N)를 4점에 고르게 나눈 **표시 근사**.
 *
 * 두 가지를 근사하고, `SURFACE_NOTES.skidDisplay`가 둘 다 말한다.
 *
 * 1. **네 점을 같이 누른다.** 엔진은 접촉점마다 다른 하중을 계산하지만 신호에는 합만
 *    실린다. 롤·피치에 따른 좌우 차이를 지어내지 않는다.
 * 2. **합에 감쇠가 섞여 있다.** `plant/ground.py`의 접촉점 하중은 `n = k·δ + c·δ̇`라,
 *    `합/4/k = δ + (c/k)·δ̇`이고 데모 값에서 `c/k = 0.1 s`다. 정지 상태에서는 정확하지만
 *    (10.8 kN → 0.05 m, `rest_penetration`과 일치) **접지 순간 δ̇ = 1.5 m/s면 0.15 m가
 *    더 얹혀** 표시가 상한에 붙는다. 실제 침하는 그보다 훨씬 얕다. 하필 사람이 스키드를
 *    보고 있는 순간이라 이쪽이 1번보다 큰 오차다.
 *
 * 감쇠를 빼려면 δ̇가 필요한데 신호에 없다. 차분으로 만들면 다운샘플(stride 14 ≈ 0.14 s)
 * 위에서 계산하게 되어 접지 같은 급변에서 더 틀린다 — **없는 정확도를 지어내지 않는다.**
 *
 * `n_gear`가 NaN이면(착륙장치 미장착) null이고 스키드를 움직이지 않는다.
 * k는 접촉점 하나의 강성 [N/m](`plant/demo.py` 기준 54 kN/m).
 */
export function skidCompression(
  nGear: Sample | undefined,
  kPerPoint = 54000,
  points = 4,
  maxTravel = 0.12,
): number | null {
  const n = finite(nGear);
  if (n === null || !(kPerPoint > 0) || !(points > 0)) return null;
  const perPoint = Math.max(n, 0) / points;
  return Math.min(perPoint / kPerPoint, maxTravel);
}
