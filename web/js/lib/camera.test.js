/** lib/camera.js — 시점 계산 테스트.

가장 중요한 것은 **체이스 지연의 프레임률 독립**이다. 프레임당 고정 비율로 섞으면
60 Hz 기계와 25 Hz 기계에서 카메라가 다르게 움직이는데, 그건 화면을 보고서는 알 수 없다.
*/

import assert from "node:assert/strict";
import { test } from "node:test";

import { eulerToQuat } from "./attitude.js";
import {
  EL_MAX, EL_MIN, JUMP_RESET_SAMPLES,
  attitudeCamera, chaseCamera, liftAboveGround, onboardCamera, orbitCamera, rotateBy,
  shouldResetSmoothing, travelDirection,
} from "./camera.js";

const LEVEL = eulerToQuat(0, 0, 0);

/* ---------- 체이스 ---------- */

test("체이스는 진행 방향 뒤 위에 선다", () => {
  const c = chaseCamera({
    pos: [0, 0, -300], vel: [88, 0, 0], q: LEVEL, prevEye: null, dist: 60, height: 20,
  });
  assert.ok(Math.abs(c.eye[0] - -60) < 1e-9, "북으로 나는 중이면 카메라는 60 m 남쪽");
  assert.ok(Math.abs(c.eye[1]) < 1e-9);
  assert.ok(Math.abs(c.eye[2] - (-300 - 20)) < 1e-9, "20 m 위 (D 음수)");
  assert.deepEqual(c.target, [0, 0, -300]);
});

test("체이스 지연은 프레임률과 무관하다 — 100 ms 한 번 == 10 ms 열 번", () => {
  const base = { pos: [1000, 0, -300], vel: [88, 0, 0], q: LEVEL, dist: 60, height: 20, tau: 0.35 };
  const start = [0, 0, 0];
  const once = chaseCamera({ ...base, prevEye: start, dtWall: 0.1 }).eye;
  let eye = start;
  for (let i = 0; i < 10; i++) eye = chaseCamera({ ...base, prevEye: eye, dtWall: 0.01 }).eye;
  for (let k = 0; k < 3; k++) {
    assert.ok(Math.abs(once[k] - eye[k]) < 1e-9, `축 ${k}: ${once[k]} vs ${eye[k]}`);
  }
});

test("dtWall이 0이면 카메라가 저절로 움직이지 않는다", () => {
  const prev = [5, 5, 5];
  const c = chaseCamera({
    pos: [1000, 0, -300], vel: [88, 0, 0], q: LEVEL, prevEye: prev, dtWall: 0,
    dist: 60, height: 20,
  });
  assert.deepEqual(c.eye, prev);
});

test("prevEye가 없으면 지연 없이 바로 목표 위치에 놓인다 (첫 프레임·리셋)", () => {
  const args = { pos: [0, 0, -300], vel: [88, 0, 0], q: LEVEL, dist: 60, height: 20 };
  assert.deepEqual(chaseCamera({ ...args, prevEye: null }).eye,
    chaseCamera({ ...args, prevEye: null, dtWall: 1e9 }).eye);
});

test("커서가 크게 뛰면 지연을 리셋한다 — 안 하면 카메라가 기어간다", () => {
  assert.equal(shouldResetSmoothing(null, 0), true);
  assert.equal(shouldResetSmoothing(100, 101), false);
  assert.equal(shouldResetSmoothing(100, 100 + JUMP_RESET_SAMPLES + 1), true);
  assert.equal(shouldResetSmoothing(100, 100 - JUMP_RESET_SAMPLES - 1), true, "뒤로 끈 것도");
});

/* ---------- 속도가 서는 구간 (발사 전·정지 후) ---------- */

test("속도가 거의 0이면 기수 방향으로 물러선다 — NaN을 흘리지 않는다", () => {
  const q = eulerToQuat(0, (15 * Math.PI) / 180, 0); // 레일 위 앙각 15°
  const d = travelDirection([0, 0, 0], q);
  assert.ok(d.every(Number.isFinite), "NaN 없음");
  assert.ok(Math.abs(Math.hypot(...d) - 1) < 1e-12, "단위벡터");
  assert.ok(d[2] < 0, "기수가 위를 향하므로 D 성분 음수");
});

test("정지 상태에서도 체이스가 유한한 카메라를 낸다 (발사 대기 화면)", () => {
  const c = chaseCamera({
    pos: [0, 0, -1.2], vel: [0, 0, 0], q: eulerToQuat(0, 0.26, 0), prevEye: null,
    dist: 40, height: 12,
  });
  assert.ok(c.eye.every(Number.isFinite));
});

/* ---------- 궤도 ---------- */

test("궤도 고각은 클램프된다 — 0이면 바닥면이 선으로 붕괴한다", () => {
  const lo = orbitCamera({ pivot: [0, 0, 0], az: 0, el: -5, dist: 100 });
  const hi = orbitCamera({ pivot: [0, 0, 0], az: 0, el: 5, dist: 100 });
  assert.ok(Math.abs(-lo.eye[2] / 100 - Math.sin(EL_MIN)) < 1e-12);
  assert.ok(Math.abs(-hi.eye[2] / 100 - Math.sin(EL_MAX)) < 1e-12);
});

test("궤도 카메라는 피벗에서 정확히 dist만큼 떨어져 있다", () => {
  const pivot = [100, -50, -300];
  const c = orbitCamera({ pivot, az: 1.1, el: 0.6, dist: 250 });
  const r = Math.hypot(c.eye[0] - pivot[0], c.eye[1] - pivot[1], c.eye[2] - pivot[2]);
  assert.ok(Math.abs(r - 250) < 1e-9, `거리 ${r}`);
});

test("방위 0은 북쪽에서 본다 — 화면의 북이 위가 되도록", () => {
  const c = orbitCamera({ pivot: [0, 0, 0], az: 0, el: EL_MIN, dist: 100 });
  assert.ok(c.eye[0] > 0 && Math.abs(c.eye[1]) < 1e-9);
});

test("rotateBy는 plot3d와 같은 손맛이고 고각만 클램프한다", () => {
  const v = rotateBy({ az: 0, el: 0.5 }, 100, 0);
  assert.ok(Math.abs(v.az - 1.2) < 1e-12, "100 px × 0.012");
  assert.equal(v.el, 0.5);
  assert.equal(rotateBy({ az: 0, el: 0.5 }, 0, -1e4).el, EL_MIN);
  assert.equal(rotateBy({ az: 0, el: 0.5 }, 0, 1e4).el, EL_MAX);
});

/* ---------- 온보드 (자세가 옳게 적용됐는지의 증거 화면) ---------- */

test("온보드는 기수 앞을 보고, 수평이면 up이 하늘을 가리킨다", () => {
  const c = onboardCamera({ pos: [0, 0, -300], q: LEVEL });
  assert.ok(c.target[0] > c.eye[0], "북쪽(기수 방향)을 본다");
  assert.ok(Math.abs(c.up[2] - -1) < 1e-12, "up이 D 음수 = 위");
});

test("롤 90°면 온보드의 up이 옆으로 눕는다 — 지평선이 기운다", () => {
  const c = onboardCamera({ pos: [0, 0, -300], q: eulerToQuat(Math.PI / 2, 0, 0) });
  // 우롤 90°: 동체 −z축(머리 위)이 NED에서 +E를 향한다
  assert.ok(Math.abs(c.up[1] - 1) < 1e-12, `up=${c.up}`);
  assert.ok(Math.abs(c.up[2]) < 1e-12);
});

test("피치가 들리면 온보드 시선도 들린다 — 지평선이 내려간다", () => {
  const c = onboardCamera({ pos: [0, 0, -300], q: eulerToQuat(0, 0.3, 0) });
  assert.ok(c.target[2] < c.eye[2], "시선 끝이 눈보다 위(D 작음)");
});

test("온보드 카메라는 기체 안이 아니라 앞에 놓인다 (기체가 시야를 가리지 않게)", () => {
  const c = onboardCamera({ pos: [0, 0, -300], q: LEVEL, offsetFrd: [1.2, 0, -0.15] });
  assert.ok(Math.abs(c.eye[0] - 1.2) < 1e-12, "기수 쪽으로 1.2 m");
  assert.ok(Math.abs(c.eye[2] - (-300 - 0.15)) < 1e-12, "0.15 m 위");
});

/* ---------- 자세 관측 ---------- */

test("자세 관측 시점은 기체를 따라다니되 방향은 월드에 고정된다", () => {
  const a = attitudeCamera({ pos: [0, 0, -300], dist: 12 });
  const b = attitudeCamera({ pos: [500, 200, -100], dist: 12 });
  const da = [a.eye[0] - 0, a.eye[1] - 0, a.eye[2] - -300];
  const db = [b.eye[0] - 500, b.eye[1] - 200, b.eye[2] - -100];
  for (let k = 0; k < 3; k++) assert.ok(Math.abs(da[k] - db[k]) < 1e-9, `축 ${k}`);
});

/* ---------- 지면 클램프 ---------- */

test("카메라는 지면 아래로 내려가지 않는다 — 내려가면 지면 판이 화면을 덮는다", () => {
  // 레일 위 정지 자세(앙각 15°)에서 "진행 방향 뒤 아래"는 정상 구성에서도 지면 밑이 된다
  const c = chaseCamera({
    pos: [0, 0, -1.2], vel: [0, 0, 0], q: eulerToQuat(0, 0.2618, 0), prevEye: null,
    dist: 320, height: 90, groundD: 0, minClearance: 3,
  });
  assert.ok(c.eye[2] <= -3, `지면 3 m 위: D=${c.eye[2]}`);
});

test("지면을 모르면(groundD null) 카메라를 옮기지 않는다 — 없는 기준으로 움직이지 않는다", () => {
  const eye = [0, 0, 100];
  assert.deepEqual(liftAboveGround(eye, null, 3), eye);
});

test("이미 지면 위면 그대로 둔다 (클램프가 시점을 끌어내리지 않는다)", () => {
  assert.deepEqual(liftAboveGround([0, 0, -500], 0, 3), [0, 0, -500]);
});

test("궤도 시점도 같은 클램프를 받는다", () => {
  const c = orbitCamera({ pivot: [0, 0, -2], az: 0, el: 0.05, dist: 500, groundD: 0 });
  assert.ok(c.eye[2] <= -3);
});

test("온보드는 클램프하지 않는다 — 기체가 실제로 지면에 서 있는 구간이 있다", () => {
  const c = onboardCamera({ pos: [0, 0, -0.5], q: eulerToQuat(0, 0, 0) });
  assert.ok(c.eye[2] > -3, "지면 근처 그대로");
});

test("속도도 자세도 없으면 북쪽으로 물러선다 — 유한한 카메라를 낸다", () => {
  const d = travelDirection(null, null);
  assert.deepEqual(d, [1, 0, 0]);
  const c = chaseCamera({
    pos: [0, 0, -100], vel: null, q: null, prevEye: null, dist: 60, height: 20,
  });
  assert.ok(c.eye.every(Number.isFinite));
});
