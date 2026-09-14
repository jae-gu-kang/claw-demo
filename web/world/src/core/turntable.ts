/** 기체 탭 대표 그림 — 턴테이블 판단 (06 §8). **three를 모른다**(06 §6 계층: 판단은 core/, 그리기는 scene/).
 *
 * ## 기체가 돌고 카메라는 선다
 *
 * 카메라를 기체 둘레로 돌리면(궤도 카메라) 조명이 월드에 고정돼 있어 반 바퀴마다 기체 윗면·옆면이 그늘로
 * 넘어간다. 제품 사진의 턴테이블처럼 **기체를 돌리고** 카메라·조명을 세워 두면 어느 각도에서나 같은 빛이다.
 * 끌기도 같은 축을 쓴다 — 가로 끌기는 기체 요, 세로 끌기는 카메라 고각이다.
 *
 * ## 줌·이동이 없다
 *
 * 대표 그림은 스크롤되는 탭 한가운데 있다. 휠을 줌으로 먹으면 페이지를 내리려던 손이 기체를 키운다.
 */

export interface TurntableView {
  /** 기체 요 [rad] — 로컬 +Y(위) 둘레, three `rotation.y`와 같은 부호(위에서 보아 반시계가 +) */
  yaw: number;
  /** 카메라 고각 [rad] — 0이면 수평에서, +면 위에서 내려다본다 */
  elev: number;
}

const TAU = 2 * Math.PI;

/** 한 바퀴 [s] — 날개 끝이 화면을 가로지르는 속도가 수치 판독을 방해하지 않는 선. 표시 선택이다 */
export const SPIN_PERIOD_S = 24;
/** 한 프레임에 반영하는 시간 상한 [s] — 배경 탭에서 돌아온 첫 프레임은 dt가 수십 초라 기체가 튄다 */
export const MAX_FRAME_DT_S = 0.1;
/** 고각 하한 — 바닥과 같은 높이로 내려가면 델타익이 선 하나로 접힌다 */
export const ELEV_MIN = 0.02;
/** 고각 상한 — 평면형이 보이는 선. π/2에 닿으면 lookAt의 위 방향이 퇴화한다 */
export const ELEV_MAX = 1.35;
/** 끌기 1 px당 회전 [rad] */
export const RAD_PER_PX = 0.009;
/** 화살표 키 한 번 [rad] — 끌 수 없는 사용자의 같은 조작 */
export const KEY_STEP = 0.2;
/** 시작 시점 — 기수가 카메라 쪽 왼편을 보는 3/4 전면. 모델 기수는 로컬 −Z라 π 돌리면 카메라(+Z)를 본다 */
export const START_VIEW: Readonly<TurntableView> = { yaw: Math.PI - 0.7, elev: 0.3 };

/** [0, 2π) */
export function wrapYaw(a: number): number {
  return ((a % TAU) + TAU) % TAU;
}

export function clampElev(e: number): number {
  return Math.min(ELEV_MAX, Math.max(ELEV_MIN, e));
}

/** 자동 회전 한 프레임. dt가 비정상(음수·NaN)이면 제자리, 크면 `MAX_FRAME_DT_S`만큼만. */
export function advanceYaw(yaw: number, dtS: number, periodS = SPIN_PERIOD_S): number {
  if (!(dtS > 0) || !(periodS > 0)) return wrapYaw(yaw);
  return wrapYaw(yaw + (TAU * Math.min(dtS, MAX_FRAME_DT_S)) / periodS);
}

/** 끌기 — 오른쪽으로 끌면 기체 앞면이 오른쪽으로 간다(요 +), 아래로 끌면 위에서 내려다본다(고각 +). */
export function dragView(v: TurntableView, dxPx: number, dyPx: number): TurntableView {
  return { yaw: wrapYaw(v.yaw + dxPx * RAD_PER_PX), elev: clampElev(v.elev + dyPx * RAD_PER_PX) };
}

/** 기체가 차지하는 원기둥 — 회전축(로컬 +Y) 둘레로 어느 요에서도 이 안에 있다. */
export interface TurntableExtent {
  /** 회전축에서 수평으로 가장 먼 거리 [m] — 경계 상자 모서리까지(√((폭/2)² + (길이/2)²)) */
  radial: number;
  /** 위아래 반높이 [m] */
  halfHeight: number;
}

/** 화면 맞춤 여유 — 1이면 가장 불리한 자세에서 가장자리에 닿는다. 머리글·사실 줄이 그림 위에 얹히므로 조금 남긴다 */
export const FIT_MARGIN = 1.12;

/** 원기둥이 **어느 요에서도** 화면에 들어오는 카메라 거리 — 세로·가로 중 더 먼 쪽.
 *
 * 경계구로 재면 납작한 기체(델타익은 높이가 길이의 1/5)가 화면 가운데 작게 남는다 — 구의 세로 지름을 기체가 쓰지
 * 않기 때문이다. 원기둥은 돌리는 축과 모양이 같아 요에 무관하면서 세로를 아낀다. 고각 e에서 화면 세로로 보이는
 * 반폭은 halfHeight·cos e + radial·sin e를 넘지 않고(위에서 볼수록 평면형이 세로를 쓴다), 카메라 쪽으로 radial만큼
 * 다가온 점이 가장 크게 보이므로 거리에서 radial을 빼고 잰다 — 둘 다 보수적이라 잘리지 않는다.
 *
 * 폭이 아직 0인 무대(숨겨진 채 붙은 경우)는 가로를 모르므로 세로로만 잰다 — 무한대 거리를 내지 않는다. */
export function fitDistance(
  ext: TurntableExtent, elev: number, vfovRad: number, aspect: number, margin = FIT_MARGIN,
): number {
  const vHalf = vfovRad / 2;
  const hHalf = aspect > 0 ? Math.atan(Math.tan(vHalf) * aspect) : vHalf;
  const vertical = ext.halfHeight * Math.cos(elev) + ext.radial * Math.sin(elev);
  const dH = ext.radial + ext.radial / Math.tan(hHalf);
  const dV = ext.radial + vertical / Math.tan(vHalf);
  return Math.max(dH, dV) * margin;
}

/** 카메라 자리 — 원점(기체 중심)에서 +Z 쪽으로 dist, 고각만큼 들어 올린다. */
export function cameraOffset(dist: number, elev: number): [number, number, number] {
  return [0, dist * Math.sin(elev), dist * Math.cos(elev)];
}
