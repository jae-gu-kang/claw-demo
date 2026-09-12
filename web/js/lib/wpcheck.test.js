import test from "node:test";
import assert from "node:assert/strict";

import { checkWaypoints, flyablePath, pathSpeed, turnRadius } from "./wpcheck.js";

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

// ---- 경로 미리보기 (선회호) ----

const R88 = (88 * 88) / (9.80665 * Math.tan(0.7)); // ≈ 937.5 m
const dist = (a, b) => Math.hypot(a.n - b.n, a.e - b.e);

test("flyablePath: 직진이면 호가 없다 — 계획선과 같은 점만 남는다", () => {
  const pts = [ok(3000, 0), ok(9000, 0)];
  const r = flyablePath(pts, 88, 0.7);
  assert.deepEqual(r.tightIdx, []);
  assert.deepEqual(r.points, [{ n: 0, e: 0 }, { n: 3000, e: 0 }, { n: 9000, e: 0 }]);
});

test("flyablePath: 90° 우선회 — 접점·중심·호가 기하적으로 맞는다", () => {
  // 원점 → (3000,0) 북진 → (3000,3000) 동진. 90° 우선회, lead = R·tan45° = R
  const r = flyablePath([ok(3000, 0), ok(3000, 3000)], 88, 0.7);
  assert.deepEqual(r.tightIdx, []);
  assert.ok(Math.abs(r.radius - R88) < 1e-9);

  // 진입 접점: 꺾임점에서 진입 방위(북)로 lead만큼 **뒤**
  const tIn = r.points[1];
  assert.ok(Math.abs(tIn.n - (3000 - R88)) < 1e-6, `tIn.n=${tIn.n}`);
  assert.ok(Math.abs(tIn.e) < 1e-6);

  // 출구 접점 = 호의 끝 = 꺾임점에서 출구 방위(동)로 lead만큼 **앞**.
  // 폴리라인은 [원점, tIn, 호 16점, 마지막 WP]라 호의 끝은 at(-1)이 아니라 1+16이다
  assert.equal(r.points.length, 1 + 1 + 16 + 1);
  const tOut = r.points[17];
  assert.ok(Math.abs(tOut.n - 3000) < 1e-6, `tOut.n=${tOut.n}`);
  assert.ok(Math.abs(tOut.e - R88) < 1e-6, `tOut.e=${tOut.e}`);
  // 마지막 점은 마지막 웨이포인트 그 자체다 (거기엔 다음 구간이 없어 호가 없다)
  assert.deepEqual(r.points.at(-1), { n: 3000, e: 3000 });

  // 중심은 두 접점에서 모두 R — 그래야 양쪽 구간에 접한다
  const ctr = { n: 3000 - R88, e: R88 };
  assert.ok(Math.abs(dist(tIn, ctr) - R88) < 1e-6);
  assert.ok(Math.abs(dist(tOut, ctr) - R88) < 1e-6);
  // 호의 모든 표본이 중심에서 R (접점 포함, 마지막 WP는 호가 아니라 제외)
  for (const p of r.points.slice(1, 18)) {
    assert.ok(Math.abs(dist(p, ctr) - R88) < 1e-6, `점 ${JSON.stringify(p)}`);
  }
  // **모서리를 안쪽으로 자른다** — 호가 꺾임점(3000,0)보다 원점 쪽에 있다
  const mid = r.points[1 + 8]; // arcSteps 16의 중간
  assert.ok(mid.n < 3000 && mid.e > 0, `mid=${JSON.stringify(mid)}`);
  assert.ok(dist(mid, { n: 3000, e: 0 }) > 300, "모서리에 붙어 있으면 자른 것이 아니다");
});

test("flyablePath: 좌선회는 호가 반대쪽으로 — 부호를 잃지 않는다", () => {
  const right = flyablePath([ok(3000, 0), ok(3000, 3000)], 88, 0.7); // 동쪽 = 우선회
  const left = flyablePath([ok(3000, 0), ok(3000, -3000)], 88, 0.7); // 서쪽 = 좌선회
  const midR = right.points[9];
  const midL = left.points[9];
  assert.ok(midR.e > 0, `우선회 중간점 E=${midR.e}`);
  assert.ok(midL.e < 0, `좌선회 중간점 E=${midL.e}`);
  // 축 대칭이라 크기는 같다 — 한쪽만 맞게 짠 코드를 잡는다
  assert.ok(Math.abs(midR.n - midL.n) < 1e-6);
  assert.ok(Math.abs(midR.e + midL.e) < 1e-6);
});

test("flyablePath: 못 나는 꺾임은 호를 지어내지 않고 표시만 한다", () => {
  // 재현했던 그 배치 — 1~2.5 km 간격 직각. checkWaypoints가 경고하는 바로 그 자리다
  const pts = [ok(2000, 0), ok(2000, 1000), ok(0, 1000), ok(0, 2500)];
  const chk = checkWaypoints(pts, 88, 0.7, 300);
  const path = flyablePath(pts, 88, 0.7);
  // 경고한 꺾임과 표시한 꺾임이 **같은 집합**이다 — 글과 그림이 같은 말을 해야 한다
  assert.deepEqual(path.tightIdx, chk.corners.filter((c) => c.tight).map((c) => c.idx));
  assert.ok(path.tightIdx.length > 0);
  // 그 자리는 계획 꼭짓점이 그대로 폴리라인에 있다 (호로 대체되지 않았다)
  for (const i of path.tightIdx) {
    assert.ok(
      path.points.some((p) => Math.abs(p.n - pts[i].n) < 1e-9 && Math.abs(p.e - pts[i].e) < 1e-9),
      `WP${i + 1} 꼭짓점이 폴리라인에 없다`,
    );
  }
});

test("flyablePath: 180° 되돌기도 호를 그리지 않는다 — lead가 무한이다", () => {
  const r = flyablePath([ok(3000, 0), ok(6000, 0), ok(0, 0)], 88, 0.7);
  assert.deepEqual(r.tightIdx, [1]);
});

test("flyablePath: 판정 불가면 빈 경로 — 없는 선을 그리지 않는다", () => {
  for (const r of [
    flyablePath([ok(3000, 0), ok(3000, 3000)], null, 0.7), // 속도 모름
    flyablePath([ok(3000, 0), ok(3000, 3000)], 88, 0), // 뱅크 한계 0
    flyablePath([], 88, 0.7),
    flyablePath(undefined, 88, 0.7),
  ]) {
    assert.deepEqual(r.points, []);
    assert.deepEqual(r.tightIdx, []);
  }
  assert.equal(flyablePath([ok(1, 1)], null, 0.7).radius, null);
});

test("flyablePath: 미완성 행(ok=false)은 기하에서 빠진다 — 판정과 같은 규약", () => {
  const withBad = [ok(3000, 0), { n: NaN, e: 0, ok: false }, ok(3000, 3000)];
  const clean = [ok(3000, 0), ok(3000, 3000)];
  assert.deepEqual(flyablePath(withBad, 88, 0.7), flyablePath(clean, 88, 0.7));
});

test("flyablePath: 느리게 날면 같은 배치가 날 수 있게 된다 — 반경이 V²이라", () => {
  const pts = [ok(2000, 0), ok(2000, 1000), ok(0, 1000), ok(0, 2500)];
  assert.ok(flyablePath(pts, 88, 0.7).tightIdx.length > 0);
  assert.deepEqual(flyablePath(pts, 30, 0.7).tightIdx, [], "30 m/s면 R≈109 m라 다 든다");
});

test("flyablePath: 장주 기본 미션은 전 구간이 날 수 있다 — 경고도 호 누락도 없다", () => {
  // simrequest.js defaultWpRows()의 장주 (활주로 축 좌표를 NED로 돌린 값)
  const h = 0.05964;
  const axis = (a, c) => ok(
    Math.round(a * Math.cos(h) - c * Math.sin(h)),
    Math.round(a * Math.sin(h) + c * Math.cos(h)),
  );
  const pts = [axis(3500, 0), axis(3500, 2200), axis(-5800, 2200), axis(-5800, 0), axis(-3600, 0)];
  assert.deepEqual(checkWaypoints(pts, 88, 0.7, 300).warnings, []);
  assert.deepEqual(flyablePath(pts, 88, 0.7).tightIdx, []);
});
