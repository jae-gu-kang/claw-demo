/** 시점 계산 — 궤적 표본과 자세에서 카메라 값을 낸다 (NED·m·rad, 렌더러 무관).

반환은 `{eye, target, up}` 셋 다 NED 성분이다. three.js 축(x=E, y=위, z=−N)으로 옮기는
일은 어댑터의 한 줄이 맡는다 — 그래야 장래 자체 WebGL2 구현이 이 모듈을 그대로 쓴다.

## 네 시점

- **chase**  기체 뒤 위에서 따라간다. 기본 시점.
- **orbit**  방위·고각·거리를 사용자가 돌린다. views/plot3d.js의 손맛을 잇는다.
- **onboard** 기체에 붙은 카메라. 롤에 따라 지평선이 기울고 피치가 지평선을 올린다 —
  자세가 옳게 적용됐는지를 눈으로 확인하는 화면이다.
- **attitude** 기체를 큼직하게 보는 근접 고정 시점. 롤·피치·요를 직접 읽는다.

## 체이스가 **속도 방향**을 쓰는 이유

동체 x축(기수) 뒤에 붙이면 롤이 카메라를 통째로 굴려 방향감각이 무너진다. 속도 방향은
롤과 무관하므로 화면이 안정적이다. 다만 속도가 거의 0인 구간(발사 전 정지, 착륙 후 정지)
에서는 방향이 정의되지 않으므로 **기수 방향으로 물러선다** — 0 벡터를 정규화해 NaN을
흘리지 않는다.
*/

import { bodyAxesNed } from "./attitude.js";

export const CAM_MODES = ["chase", "orbit", "onboard", "attitude"];

export const FOV_Y = (55 * Math.PI) / 180; // [rad] 수직 화각 — 네 시점 공통
export const EL_MIN = 0.05; // 궤도 고각 하한 [rad] — 0이면 바닥면이 선으로 붕괴 (plot3d와 같은 값)
export const EL_MAX = Math.PI / 2 - 0.02;
export const ROT_PER_PX = 0.012; // 드래그 1 px당 회전 [rad] — plot3d와 같은 손맛

/** 속도가 이보다 느리면 방향이 정의되지 않는다고 본다 [m/s]. */
const SPEED_EPS = 1.0;
/** 커서가 이보다 크게 뛰면(슬라이더를 확 끌었다) 지연을 리셋한다 [샘플]. */
export const JUMP_RESET_SAMPLES = 25;

/** 체이스 시점.
 *
 * `prevEye`가 null이면 즉시 목표 위치에 놓는다(첫 프레임·리셋). 아니면 지수 감쇠로
 * 따라간다 — **감쇠 계수를 `1 − exp(−dt/τ)`로 잡아 프레임률과 무관**하게 만든다.
 * 프레임당 고정 비율로 섞으면 60 Hz와 25 Hz에서 카메라가 다르게 움직인다.
 */
/**
 * @param {object} a
 * @param {number[]} a.pos NED
 * @param {number[]|null} a.vel NED 속도 — null이면 기수로 물러선다
 * @param {number[]|null} a.q 쿼터니언 [w, x, y, z] — null이면 travelDirection이 북으로 물러선다
 * @param {number[]|null} a.prevEye 직전 시점 — null이면 즉시 목표 위치
 * @param {number} [a.dtWall] 실시간 경과 [s]
 * @param {number} a.dist 뒤로 거리 [m]
 * @param {number} a.height 위로 높이 [m]
 * @param {number} [a.tau] 지연 시상수 [s]
 * @param {number|null} [a.groundD] 지면 D [m]
 * @param {number} [a.minClearance] 지면 여유 [m]
 */
export function chaseCamera({
  pos, vel, q, prevEye, dtWall = 0, dist, height, tau = 0.35,
  groundD = null, minClearance = 3,
}) {
  const back = travelDirection(vel, q);
  const desired = [
    pos[0] - back[0] * dist,
    pos[1] - back[1] * dist,
    pos[2] - back[2] * dist - height, // D 음수 = 위
  ];
  const eye = prevEye == null ? desired : smooth(prevEye, desired, dtWall, tau);
  return { eye: liftAboveGround(eye, groundD, minClearance), target: [...pos], up: [0, 0, -1], fovY: FOV_Y };
}

/** 카메라를 지면 위로 들어 올린다 — 아래로 내려가면 지면 판이 화면을 덮어 아무것도 안 보인다.
 *
 * 기수를 크게 든 채(레일 앙각 15°) 정지해 있으면 "진행 방향 뒤 아래"가 지면 밑이 되는데,
 * 그것이 정상 구성에서도 일어난다. D는 아래가 양수이므로 지면 위 = 더 작은 D.
 * groundD가 null이면(지면을 모르면) 손대지 않는다 — 없는 기준으로 옮기지 않는다.
 */
export function liftAboveGround(eye, groundD, minClearance) {
  if (groundD == null) return eye;
  return [eye[0], eye[1], Math.min(eye[2], groundD - minClearance)];
}

/** 궤도 시점 — 피벗을 중심으로 방위 az·고각 el·거리 dist.
 *
 * @param {object} a
 * @param {number[]} a.pivot NED
 * @param {number} a.az 방위 [rad]
 * @param {number} a.el 고각 [rad]
 * @param {number} a.dist 거리 [m]
 * @param {number|null} [a.groundD] 지면 D [m] — 주면 그 위로 들어 올린다
 * @param {number} [a.minClearance] 지면 여유 [m]
 */
export function orbitCamera({ pivot, az, el, dist, groundD = null, minClearance = 3 }) {
  const e = clamp(el, EL_MIN, EL_MAX);
  const horiz = Math.cos(e) * dist;
  return {
    eye: liftAboveGround([
      pivot[0] + horiz * Math.cos(az),
      pivot[1] + horiz * Math.sin(az),
      pivot[2] - Math.sin(e) * dist,
    ], groundD, minClearance),
    target: [...pivot],
    up: [0, 0, -1],
    fovY: FOV_Y,
  };
}

/** 온보드 1인칭 — 기체 자세를 그대로 쓴다.
 *
 * `up`이 동체 −z축이라 **롤에 따라 지평선이 기운다**. 이것이 자세가 옳게 적용됐는지의
 * 가장 직접적인 증거 화면이다. offsetFrd는 CG 기준 카메라 위치 [m, FRD].
 */
/**
 * @param {object} a
 * @param {number[]} a.pos NED
 * @param {number[]} a.q 쿼터니언 [w, x, y, z]
 * @param {number[]} [a.offsetFrd] 동체축 오프셋 [m]
 * @param {number} [a.lookAhead] 전방 주시 거리 [m]
 */
export function onboardCamera({ pos, q, offsetFrd = [1.2, 0, -0.15], lookAhead = 200 }) {
  const ax = bodyAxesNed(q);
  const eye = [
    pos[0] + ax.forward[0] * offsetFrd[0] + ax.right[0] * offsetFrd[1] + ax.down[0] * offsetFrd[2],
    pos[1] + ax.forward[1] * offsetFrd[0] + ax.right[1] * offsetFrd[1] + ax.down[1] * offsetFrd[2],
    pos[2] + ax.forward[2] * offsetFrd[0] + ax.right[2] * offsetFrd[1] + ax.down[2] * offsetFrd[2],
  ];
  return {
    eye,
    target: [
      eye[0] + ax.forward[0] * lookAhead,
      eye[1] + ax.forward[1] * lookAhead,
      eye[2] + ax.forward[2] * lookAhead,
    ],
    up: [-ax.down[0], -ax.down[1], -ax.down[2]],
    fovY: FOV_Y,
  };
}

/** 자세 관측 근접 시점 — 월드 고정 방향에서 기체를 크게 본다(기체는 회전, 시점은 고정).
 *
 * @param {object} a
 * @param {number[]} a.pos NED
 * @param {number} [a.az] 방위 [rad]
 * @param {number} [a.el] 고각 [rad]
 * @param {number} a.dist 거리 [m]
 * @param {number|null} [a.groundD] 지면 D [m]
 */
export function attitudeCamera({ pos, az = 2.4, el = 0.35, dist, groundD = null }) {
  return orbitCamera({ pivot: pos, az, el, dist, groundD, minClearance: 1 });
}

/** 드래그 픽셀 → 새 {az, el} (고각 클램프 포함). views/plot3d.js와 같은 규약. */
export function rotateBy(view, dxPx, dyPx) {
  return {
    az: view.az + dxPx * ROT_PER_PX,
    el: clamp(view.el + dyPx * ROT_PER_PX, EL_MIN, EL_MAX),
  };
}

/** 커서가 크게 뛰었는가 — 참이면 체이스 지연을 리셋해야 한다(안 하면 카메라가 기어간다). */
export function shouldResetSmoothing(prevIdx, idx) {
  return prevIdx == null || Math.abs(idx - prevIdx) > JUMP_RESET_SAMPLES;
}

/** 궤적 진행 방향 단위벡터 — 속도가 서면 기수 방향으로, 자세도 없으면 북쪽으로.
 *
 * 마지막 폴백(북)은 **자료에 대한 주장이 아니라 화면 배치**다: 속도도 자세도 모르면
 * 진행 방향이라는 것이 존재하지 않고, 그때 카메라를 어디에 둘지는 표시 선택일 뿐이다.
 * 그래도 카메라 위치는 유한해야 하므로 한 방향을 고른다(NaN을 흘리지 않는다).
 */
export function travelDirection(vel, q) {
  const speed = vel == null ? 0 : Math.hypot(vel[0], vel[1], vel[2]);
  if (speed >= SPEED_EPS) return [vel[0] / speed, vel[1] / speed, vel[2] / speed];
  if (q == null) return [1, 0, 0];
  return bodyAxesNed(q).forward;
}

function smooth(prev, desired, dtWall, tau) {
  // dt가 0이면 alpha = 0 — 정지 화면에서 카메라가 저절로 움직이지 않는다
  const alpha = tau > 0 ? 1 - Math.exp(-Math.max(dtWall, 0) / tau) : 1;
  return [
    prev[0] + (desired[0] - prev[0]) * alpha,
    prev[1] + (desired[1] - prev[1]) * alpha,
    prev[2] + (desired[2] - prev[2]) * alpha,
  ];
}

function clamp(v, lo, hi) {
  return Math.min(Math.max(v, lo), hi);
}
