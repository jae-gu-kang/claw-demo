/** `web/js/lib/attitude.js`의 **타입 있는 얼굴** — 사본이 아니라 얇은 어댑터다.
 *
 * ## 왜 포팅하지 않나
 *
 * 그 모듈은 `views/sim.js`·`views/world.js`와 공유하고 `attitude.test.js`가 시험한다.
 * TS로 옮기면 **세 번째 구현**이 생기고 테스트는 여전히 옛 `.js`를 보므로 "어댑터가
 * 바뀌어도 테스트는 계속 초록"인 상태가 된다 — `lib/world3d.js` 머리말이 `nedToRender`를
 * lib에 둔 이유로 든 그 상태다.
 *
 * ## 왜 그냥 import하지 않나
 *
 * `allowJs`로 부를 수는 있는데 `noUncheckedIndexedAccess` 아래서 배열 반환이
 * `(number | undefined)[]`로 추론된다. 그 느슨함을 호출부마다 풀면 단언이 흩어지고,
 * 한 곳만 틀려도 조용히 `undefined`가 좌표로 흘러든다. **좁히기를 여기 한 곳에 모은다.**
 *
 * ## 던지지 않고 null을 낸다
 *
 * 이 계층의 나머지(`surfacePose`·`launcherPose`·`finite`)가 전부 결측에 null을 내므로
 * 여기만 던지면 계약이 갈린다. 게다가 이 함수들은 rAF 콜백 안에서 불리는데, 거기서
 * 던지면 **그리지 않는 것으로 끝나지 않고 루프가 죽는다.** 화면이 한 프레임 비는 것과
 * 영영 멈추는 것은 다른 실패다.
 *
 * `NaN`도 결측으로 본다 — `typeof NaN === "number"`라 타입 검사만으로는 안 걸리고,
 * 통과시키면 three 행렬이 통째로 NaN이 되어 메시가 컬링으로 사라진다(원인이 안 보인다).
 */

import { bodyAxesNed as rawBodyAxesNed, eulerToQuat as rawEulerToQuat } from "../../../js/lib/attitude.js";

export type Vec3 = [number, number, number];
export type Quat = [number, number, number, number];

/** 동체축 셋 — 각 성분은 NED [n, e, d]. */
export interface BodyAxes {
  forward: Vec3;
  right: Vec3;
  down: Vec3;
}

const finite3 = (v: readonly (number | undefined)[]): Vec3 | null => {
  const [a, b, c] = v;
  return (typeof a === "number" && Number.isFinite(a)
    && typeof b === "number" && Number.isFinite(b)
    && typeof c === "number" && Number.isFinite(c)) ? [a, b, c] : null;
};

/** 3-2-1 오일러 (φ, θ, ψ) [rad] → q_nb [w, x, y, z]. 입력이 유한하지 않으면 null. */
export function eulerToQuat(phi: number, theta: number, psi: number): Quat | null {
  if (!Number.isFinite(phi) || !Number.isFinite(theta) || !Number.isFinite(psi)) return null;
  const q = rawEulerToQuat(phi, theta, psi) as (number | undefined)[];
  const [w, x, y, z] = q;
  if (typeof w !== "number" || !Number.isFinite(w)
    || typeof x !== "number" || !Number.isFinite(x)
    || typeof y !== "number" || !Number.isFinite(y)
    || typeof z !== "number" || !Number.isFinite(z)) return null;
  return [w, x, y, z];
}

/** q_nb → 동체축의 NED 성분. 쿼터니언이 성하지 않으면 null.
 *
 * 영 쿼터니언에서 원본 lib이 던지므로 여기서 받아 null로 바꾼다 — 호출측이 다른 결측과
 * 같은 방식으로 다루게 하려는 것이다. */
export function bodyAxesNed(q: readonly number[] | null): BodyAxes | null {
  if (q == null || q.length !== 4 || !q.every((v) => Number.isFinite(v))) return null;
  let a: { forward: (number | undefined)[]; right: (number | undefined)[]; down: (number | undefined)[] };
  try {
    a = rawBodyAxesNed(q as number[]);
  } catch {
    return null; // 영 쿼터니언 등 — lib이 던지는 자리
  }
  const forward = finite3(a.forward);
  const right = finite3(a.right);
  const down = finite3(a.down);
  return forward && right && down ? { forward, right, down } : null;
}
