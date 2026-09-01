/** lib/attitude.js — 자세 표현 테스트.

두 가지를 겨눈다. ① 엔진(claw.common.attitude)과 **같은 수**를 내는가 — 기준값은 엔진에서
직접 뽑아 아래에 박아 두었다. ② 부호·축 규약이 **말이 되는가** — 렌더러 없이도 "요 90°면
기수가 동쪽을 본다"를 검증할 수 있다는 것이 이 층을 순수하게 유지한 대가다.
*/

import assert from "node:assert/strict";
import { test } from "node:test";

import {
  SINGULAR_THETA, bodyAxesNed, bodyToNed, eulerToQuat, isNearSingular, nedToBody, quatToDcm,
} from "./attitude.js";

const HALF_PI = Math.PI / 2;

/** 엔진 claw.common.attitude에서 직접 뽑은 기준값 — 두 구현이 갈라지면 여기가 빨개진다.
 *  fwd·right·down은 C_bn의 세 행, 곧 동체축의 NED 성분이다. */
const ENGINE_REF = [
  { phi: 0, theta: 0, psi: 0,
    q: [1, 0, 0, 0],
    fwd: [1, 0, 0], right: [0, 1, 0], down: [0, 0, 1] },
  { phi: 0.1, theta: 0.2, psi: 0.3,
    q: [0.9833474432563558, 0.034270798550482096, 0.10602051106179562, 0.1435721750273919],
    fwd: [0.9362933635841992, 0.2896294776255156, -0.19866933079506122],
    right: [-0.27509584731824377, 0.9564250858492325, 0.0978433950072557],
    down: [0.21835066314633444, -0.03695701352462507, 0.9751703272018158] },
  { phi: HALF_PI, theta: 0, psi: 0,
    q: [0.7071067811865476, 0.7071067811865475, 0, 0],
    fwd: [1, 0, 0], right: [0, 0, 1], down: [0, -1, 0] },
  { phi: 0, theta: -HALF_PI, psi: 0,
    q: [0.7071067811865476, 0, -0.7071067811865475, 0],
    fwd: [0, 0, 1], right: [0, 1, 0], down: [-1, 0, 0] },
  { phi: 0, theta: 0, psi: HALF_PI,
    q: [0.7071067811865476, 0, 0, 0.7071067811865475],
    fwd: [0, 1, 0], right: [-1, 0, 0], down: [0, 0, 1] },
  { phi: -0.4, theta: 0.6, psi: -2.0,
    q: [0.5552848994337447, 0.1411675523754643, 0.3161953529528465, -0.7561421171897525],
    fwd: [-0.3434608052343533, -0.7504755509049623, -0.5646424733950353],
    right: [0.9290216471003598, -0.18335835846376192, -0.3214008270064177],
    down: [0.13767154566831985, -0.6349536675028881, 0.7601844418546907] },
];

const EPS = 1e-12;

test("eulerToQuat이 엔진과 같은 쿼터니언을 낸다 (scalar-first, 3-2-1)", () => {
  for (const c of ENGINE_REF) {
    const q = eulerToQuat(c.phi, c.theta, c.psi);
    close3(q.slice(0, 3), c.q.slice(0, 3), `q ${label(c)}`);
    assert.ok(Math.abs(q[3] - c.q[3]) < EPS, `q3 ${label(c)}`);
  }
});

test("bodyAxesNed가 엔진 C_bn의 세 행과 일치한다", () => {
  for (const c of ENGINE_REF) {
    const ax = bodyAxesNed(eulerToQuat(c.phi, c.theta, c.psi));
    close3(ax.forward, c.fwd, `forward ${label(c)}`);
    close3(ax.right, c.right, `right ${label(c)}`);
    close3(ax.down, c.down, `down ${label(c)}`);
  }
});

/* ---------- 규약이 말이 되는가 (렌더러 없이 검증하는 자리) ---------- */

test("요 90°면 기수가 동쪽을 본다", () => {
  const ax = bodyAxesNed(eulerToQuat(0, 0, HALF_PI));
  close3(ax.forward, [0, 1, 0], "기수");
});

test("롤 90°면 오른쪽 날개 끝이 아래를 향한다", () => {
  const ax = bodyAxesNed(eulerToQuat(HALF_PI, 0, 0));
  close3(ax.right, [0, 0, 1], "우익");
});

test("피치 −90°면 기수가 아래를 향한다", () => {
  const ax = bodyAxesNed(eulerToQuat(0, -HALF_PI, 0));
  close3(ax.forward, [0, 0, 1], "기수");
});

test("피치 +90°면 기수가 위를 향한다", () => {
  const ax = bodyAxesNed(eulerToQuat(0, HALF_PI, 0));
  close3(ax.forward, [0, 0, -1], "기수 (D축 음수 = 위)");
});

/* ---------- 회전의 구조 ---------- */

test("C_bn은 직교정규다 — 기체 형상이 늘어나거나 뒤집히지 않는다", () => {
  for (const c of ENGINE_REF) {
    const ax = bodyAxesNed(eulerToQuat(c.phi, c.theta, c.psi));
    for (const v of [ax.forward, ax.right, ax.down]) {
      assert.ok(Math.abs(Math.hypot(...v) - 1) < 1e-12, `단위길이 ${label(c)}`);
    }
    assert.ok(Math.abs(dot(ax.forward, ax.right)) < 1e-12, `직교 f·r ${label(c)}`);
    assert.ok(Math.abs(dot(ax.right, ax.down)) < 1e-12, `직교 r·d ${label(c)}`);
    assert.ok(Math.abs(dot(ax.down, ax.forward)) < 1e-12, `직교 d·f ${label(c)}`);
    // 오른손 좌표계 — forward × right = down 이어야 한다. 뒤집히면 기체가 거울상이 된다
    close3(cross(ax.forward, ax.right), ax.down, `오른손 ${label(c)}`);
  }
});

test("bodyToNed와 nedToBody는 서로의 역이다", () => {
  const q = eulerToQuat(-0.4, 0.6, -2.0);
  const v = [3, -7, 11];
  close3(nedToBody(q, bodyToNed(q, v)), v, "왕복");
  close3(bodyToNed(q, nedToBody(q, v)), v, "역왕복");
});

test("bodyToNed는 동체 단위축을 bodyAxesNed와 같은 곳으로 보낸다", () => {
  const q = eulerToQuat(0.1, 0.2, 0.3);
  const ax = bodyAxesNed(q);
  close3(bodyToNed(q, [1, 0, 0]), ax.forward, "x_FRD");
  close3(bodyToNed(q, [0, 1, 0]), ax.right, "y_FRD");
  close3(bodyToNed(q, [0, 0, 1]), ax.down, "z_FRD");
});

test("영 쿼터니언은 조용히 통과하지 않고 던진다", () => {
  assert.throws(() => quatToDcm([0, 0, 0, 0]), /정규화/);
});

/* ---------- 짐벌락 표시 ---------- */

test("θ가 85°를 넘으면 특이점 부근이라고 알린다", () => {
  assert.equal(isNearSingular(0), false);
  assert.equal(isNearSingular(SINGULAR_THETA - 1e-9), false);
  assert.equal(isNearSingular(SINGULAR_THETA + 1e-9), true);
  assert.equal(isNearSingular(-HALF_PI), true);
});

test("특이점에서도 회전 자체는 옳다 — φ·ψ가 불정일 뿐", () => {
  // θ=90°에서 (φ, ψ)와 (φ+δ, ψ+δ)는 다른 각이지만 **같은 회전**이다.
  // 그림이 옳다는 근거가 이것이고, 화면은 isNearSingular로 그 사실만 밝히면 된다.
  const a = bodyAxesNed(eulerToQuat(0.3, HALF_PI, 0.7));
  const b = bodyAxesNed(eulerToQuat(0.3 + 0.5, HALF_PI, 0.7 + 0.5));
  close3(a.forward, b.forward, "기수");
  close3(a.right, b.right, "우익");
});

function close3(got, want, what) {
  for (let i = 0; i < 3; i++) {
    assert.ok(Math.abs(got[i] - want[i]) < 1e-12, `${what}[${i}]: ${got[i]} != ${want[i]}`);
  }
}
function dot(a, b) { return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]; }
function cross(a, b) {
  return [a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0]];
}
function label(c) { return `(${c.phi}, ${c.theta}, ${c.psi})`; }
