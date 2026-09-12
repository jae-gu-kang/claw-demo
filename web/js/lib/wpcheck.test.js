import test from "node:test";
import assert from "node:assert/strict";

import { checkWaypoints, pathSpeed, turnRadius } from "./wpcheck.js";

const ok = (n, e) => ({ n, e, ok: true });

test("turnRadius: V²/(g·tan φ) — 재현 실측과 같은 자리", () => {
  // 88 m/s · φ 0.7 rad → 940 m 안팎 (engine guidance/path.py 머리말의 그 수)
  const r = turnRadius(88, 0.7);
  assert.ok(Math.abs(r - 940) < 15, `R=${r}`);
  // 속도가 두 배면 반경은 네 배 — V²이 판정을 지배한다
  assert.ok(Math.abs(turnRadius(176, 0.7) / r - 4) < 1e-9);
});

test("turnRadius: 판정할 수 없는 입력은 null이지 0이 아니다", () => {
  for (const [v, b] of [[0, 0.7], [-1, 0.7], [NaN, 0.7], [88, 0], [88, NaN]]) {
    assert.equal(turnRadius(v, b), null, `${v}/${b}`);
  }
});

test("pathSpeed: path 헤딩 모드의 속도, 여럿이면 가장 빠른 쪽", () => {
  const rows = [
    { heading: "0.1", speed: "200" }, // path가 아니다 — 무시
    { heading: "path", speed: "88" },
    { heading: "path", speed: "110" }, // 더 빠르다 → 이쪽이 이긴다
  ];
  assert.equal(pathSpeed(rows), 110);
  assert.equal(pathSpeed([{ heading: "path", speed: "" }]), null);
  assert.equal(pathSpeed([]), null);
  assert.equal(pathSpeed(undefined), null);
});

test("checkWaypoints: 급한 직각 꺾임을 잡아낸다 (재현한 그 배치)", () => {
  // 사용자 보고를 재현한 좌표 — 1~2.5 km 간격 직각. 엔진 실측에서 4개 중 1개만 잡았다
  const pts = [ok(2000, 0), ok(2000, 1000), ok(0, 1000), ok(0, 2500)];
  const r = checkWaypoints(pts, 88, 0.7, 100);
  assert.ok(r.radius > 900 && r.radius < 960);
  assert.ok(r.warnings.length >= 1, "급한 꺾임 경고가 있어야 한다");
  assert.ok(r.corners.some((c) => c.tight), "tight 꺾임이 표시돼야 한다");
  // 90° 꺾임의 예상 거리는 R·tan45° = R이고, 구간 절반(500 m)을 크게 넘는다
  const c0 = r.corners[0];
  assert.ok(Math.abs(c0.turnDeg - 90) < 1, `turnDeg=${c0.turnDeg}`);
  assert.ok(Math.abs(c0.lead - r.radius) < 1, `lead=${c0.lead}`);
  assert.equal(c0.tight, true);
});

test("checkWaypoints: 넉넉한 배치는 조용하다 — 경고가 장식이 되지 않게", () => {
  // 엔진에서 3/3 포획하고 정상 완주한 그 배치
  const pts = [ok(5000, 0), ok(9000, 3000), ok(13000, 3000)];
  const r = checkWaypoints(pts, 88, 0.7, 600);
  assert.deepEqual(r.warnings, []);
  assert.ok(r.corners.every((c) => !c.tight));
});

test("checkWaypoints: 같은 배치도 느리게 날면 풀린다 — 반경이 V²이라", () => {
  const pts = [ok(2000, 0), ok(2000, 1000), ok(0, 1000), ok(0, 2500)];
  const fast = checkWaypoints(pts, 88, 0.7, 400);
  const slow = checkWaypoints(pts, 30, 0.7, 400);
  assert.ok(fast.corners[0].tight);
  assert.equal(slow.corners[0].tight, false, "30 m/s면 R≈109 m라 500 m 안에 든다");
});

test("checkWaypoints: 180° 되돌기는 유한한 예상 거리가 없다", () => {
  const pts = [ok(3000, 0), ok(6000, 0), ok(0, 0)];
  const r = checkWaypoints(pts, 88, 0.7, 200);
  const c = r.corners.find((x) => x.turnDeg > 179);
  assert.ok(c, "180° 꺾임이 잡혀야 한다");
  assert.equal(c.lead, Infinity);
  assert.equal(c.tight, true);
  assert.ok(r.warnings[0].includes("되돌기"), r.warnings[0]);
});

test("checkWaypoints: 도달 반경이 선회 반경에 비해 작으면 따로 경고", () => {
  // 꺾임은 완만해 tight가 없는데도 마지막 점을 못 잡는 자리가 남는다
  const pts = [ok(20000, 0), ok(40000, 1000)];
  const r = checkWaypoints(pts, 88, 0.7, 50);
  assert.ok(r.corners.every((c) => !c.tight), "꺾임 자체는 완만하다");
  assert.equal(r.warnings.length, 1);
  assert.ok(r.warnings[0].includes("도달 반경"), r.warnings[0]);
  // 넉넉하면 그 경고도 사라진다
  assert.deepEqual(checkWaypoints(pts, 88, 0.7, 400).warnings, []);
});

test("checkWaypoints: 판정 불가는 빈 결과 — 없는 판정선을 지어내지 않는다", () => {
  const pts = [ok(2000, 0), ok(2000, 1000), ok(0, 1000)];
  for (const r of [
    checkWaypoints(pts, null, 0.7, 100), // 속도 모름 (path 모드 없음)
    checkWaypoints(pts, 88, 0, 100), // 뱅크 한계 0
    checkWaypoints([ok(1, 1)], 88, 0.7, 100), // 꺾임이 생길 수 없다
    checkWaypoints([], 88, 0.7, 100),
  ]) {
    assert.deepEqual(r.warnings, []);
    assert.deepEqual(r.corners, []);
  }
  assert.equal(checkWaypoints(pts, null, 0.7, 100).radius, null);
});

test("checkWaypoints: 미완성 행(ok=false)은 기하에서 빠진다", () => {
  const withBad = [ok(5000, 0), { n: NaN, e: 0, ok: false }, ok(9000, 3000), ok(13000, 3000)];
  const clean = [ok(5000, 0), ok(9000, 3000), ok(13000, 3000)];
  assert.deepEqual(
    checkWaypoints(withBad, 88, 0.7, 600).corners,
    checkWaypoints(clean, 88, 0.7, 600).corners,
  );
});
