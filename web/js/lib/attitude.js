/** 자세 표현 — 3-2-1 오일러 → 쿼터니언 → 동체축의 NED 성분 (규약 §2, 엔진 common/attitude.py의 짝).

3D 월드가 기체를 기울여 그리려면 φ·θ·ψ를 회전으로 바꿔야 한다. 규약은 엔진과 같다:
쿼터니언 **scalar-first (w, x, y, z)**, Hamilton, `q_nb` = NED→동체, 오일러 **3-2-1 (ψ→θ→φ)**.

## 왜 쿼터니언을 재구성하나

시뮬 신호에는 φ·θ·ψ만 있고 쿼터니언이 없다. 신호에 쿼터니언을 더하면 저장 결과가 배열
4개만큼 커지는데, 재구성이 정확하므로 그럴 이유가 없다 — 엔진이 `quat_to_euler`로 뽑은
각이라 같은 회전으로 되돌아온다. θ = ±90° 부근에서 φ·ψ는 **불정**이지만 그 조합이 나타내는
**회전 자체는 같으므로 그림은 옳다**(변화율만 튄다). `isNearSingular`가 화면이 그 사실을
말할 수 있게 한다.

## 이 파일은 렌더러를 모른다

반환은 전부 NED 성분 `[n, e, d]`다. three.js 축(x=E, y=위, z=−N)으로 옮기는 일은 어댑터의
한 줄이 맡는다 — 그래야 장래 자체 WebGL2 구현이 이 모듈을 그대로 쓴다.
*/

/** θ가 여기 넘으면 φ·ψ가 수치적으로 불정 — 화면이 그 사실을 밝혀야 한다 [rad]. */
export const SINGULAR_THETA = (85 * Math.PI) / 180;

/** 3-2-1 오일러 (φ 롤, θ 피치, ψ 요) → q_nb [w, x, y, z]. 엔진 euler_to_quat와 같은 식. */
export function eulerToQuat(phi, theta, psi) {
  const cphi = Math.cos(phi / 2), sphi = Math.sin(phi / 2);
  const cth = Math.cos(theta / 2), sth = Math.sin(theta / 2);
  const cpsi = Math.cos(psi / 2), spsi = Math.sin(psi / 2);
  return [
    cphi * cth * cpsi + sphi * sth * spsi,
    sphi * cth * cpsi - cphi * sth * spsi,
    cphi * sth * cpsi + sphi * cth * spsi,
    cphi * cth * spsi - sphi * sth * cpsi,
  ];
}

/** q_nb → C_bn (v_b = C_bn · v_n). 행 우선 9원소. 엔진 quat_to_dcm과 같은 식. */
export function quatToDcm(q) {
  const [w, x, y, z] = normalize(q);
  return [
    1 - 2 * (y * y + z * z), 2 * (x * y + w * z), 2 * (x * z - w * y),
    2 * (x * y - w * z), 1 - 2 * (x * x + z * z), 2 * (y * z + w * x),
    2 * (x * z + w * y), 2 * (y * z - w * x), 1 - 2 * (x * x + y * y),
  ];
}

/** 동체축 세 개를 **NED 성분**으로 — {forward, right, down}, 각각 [n, e, d] 단위벡터.
 *
 * C_bn의 각 **행**이 곧 그 동체축의 NED 성분이다(v_b = C_bn·v_n이므로 행 i는 동체축 i가
 * NED 축들과 이루는 방향코사인). 이것이 이 모듈이 내는 유일한 기하이고, 기체 형상의 모든
 * 꼭짓점은 이 셋의 선형결합으로 놓인다.
 */
export function bodyAxesNed(q) {
  const m = quatToDcm(q);
  return {
    forward: [m[0], m[1], m[2]],
    right: [m[3], m[4], m[5]],
    down: [m[6], m[7], m[8]],
  };
}

/** 동체 성분 [x, y, z]_FRD → NED 성분 [n, e, d]. v_n = C_bn^T · v_b. */
export function bodyToNed(q, v) {
  const m = quatToDcm(q);
  return [
    m[0] * v[0] + m[3] * v[1] + m[6] * v[2],
    m[1] * v[0] + m[4] * v[1] + m[7] * v[2],
    m[2] * v[0] + m[5] * v[1] + m[8] * v[2],
  ];
}

/** NED 성분 [n, e, d] → 동체 성분 [x, y, z]_FRD. v_b = C_bn · v_n. */
export function nedToBody(q, v) {
  const m = quatToDcm(q);
  return [
    m[0] * v[0] + m[1] * v[1] + m[2] * v[2],
    m[3] * v[0] + m[4] * v[1] + m[5] * v[2],
    m[6] * v[0] + m[7] * v[1] + m[8] * v[2],
  ];
}

/** θ가 짐벌락 부근인가 — 참이면 φ·ψ 표시값을 믿을 수 없다(회전 자체는 옳다). */
export function isNearSingular(theta) {
  return Math.abs(theta) > SINGULAR_THETA;
}

function normalize(q) {
  const n = Math.hypot(q[0], q[1], q[2], q[3]);
  if (n === 0) throw new Error("영 쿼터니언은 정규화 불가");
  return [q[0] / n, q[1] / n, q[2] / n, q[3] / n];
}
