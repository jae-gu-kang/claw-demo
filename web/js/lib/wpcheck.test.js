import test from "node:test";
import assert from "node:assert/strict";

import { readFile } from "node:fs/promises";

import {
  CLIMB_THRUST_CAP, checkWaypoints, climbGradientMax, flyablePath, pathSpeed, turnRadius,
} from "./wpcheck.js";

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

// ── 상승 경사 판정 ────────────────────────────────────────────────────────────
// 고도가 있는 점만 판정에 든다 — 위 테스트들의 `ok()`는 d가 없어 조용하다(그 자체가
// 회귀 방지다: 고도 안 쓰는 미션에 새 경고가 새면 기존 단언이 깨진다).

const okd = (n, e, d) => ({ n, e, ok: true, d });

test("checkWaypoints: 성능보다 급한 상승을 잡아낸다", () => {
  // 88 m/s 고도 루프의 실측 한계는 약 4 %다. 2 km 안에 400 m는 20 %를 요구한다
  const pts = [okd(4000, 0, 200), okd(6000, 0, 600)];
  const r = checkWaypoints(pts, 88, 0.7, 300, 0.04);
  const c = r.climbs.find((x) => x.idx === 1);
  assert.ok(c, "둘째 구간 판정이 있어야 한다");
  assert.equal(c.steep, true, `grad=${c.grad}`);
  assert.ok(r.warnings.some((w) => w.includes("상승이 지금 설정으로는 급합니다")),
    `경고 없음: ${r.warnings.join(" | ")}`);
});

test("checkWaypoints: 성능 안에 드는 상승은 조용하다 — 경고가 장식이 되지 않게", () => {
  // 20 km 안에 400 m = 2 % — 한계의 절반. 엔진 실측에서 따라온 그 경사다
  const pts = [okd(4000, 0, 200), okd(24000, 0, 600)];
  const r = checkWaypoints(pts, 88, 0.7, 300, 0.04);
  assert.equal(r.climbs.find((x) => x.idx === 1).steep, false);
  assert.deepEqual(r.warnings, []);
});

test("checkWaypoints: **첫 구간은 판정하지 않는다** — 진입 고도를 모른다", () => {
  // 첫 구간에 아무리 급한 상승을 넣어도 climbs에 없다. 안전해서가 아니라 못 재서다 —
  // 이 단언이 깨지면 누군가 진입 고도를 지어낸 것이다
  const pts = [okd(500, 0, 5000), okd(20000, 0, 5100)];
  const r = checkWaypoints(pts, 88, 0.7, 300, 0.04);
  assert.equal(r.climbs.some((c) => c.idx === 0), false);
  assert.deepEqual(r.warnings, []);
});

test("checkWaypoints: 강하는 판정하지 않는다 — 다른 물리라 같은 상수로 재면 틀린다", () => {
  const pts = [okd(4000, 0, 3000), okd(6000, 0, 200)];
  const r = checkWaypoints(pts, 88, 0.7, 300, 0.04);
  assert.deepEqual(r.climbs, [], "내려가는 구간은 climbs에 들지 않는다");
  assert.deepEqual(r.warnings, []);
});

test("checkWaypoints: 고도 없는 점은 건너뛴다 — 0으로 위장하지 않는다", () => {
  // d가 null인 점이 끼면 그 구간만 빠지고, 0 m로 읽어 거대한 강하/상승을 지어내지 않는다
  const pts = [okd(4000, 0, 200), { n: 6000, e: 0, ok: true, d: null }, okd(8000, 0, 240)];
  const r = checkWaypoints(pts, 88, 0.7, 300, 0.04);
  assert.deepEqual(r.climbs, []);
  assert.deepEqual(r.warnings, []);
});

test("checkWaypoints: 램프 분모는 **선회 예상 거리**까지 뺀다 — 엔진과 같은 분모", () => {
  // 급한 꺾임은 램프도 앞당겨 짧게 만든다. 도달 반경만으로 재면 통과하는 배치가
  // 실제 분모(예상 거리 940 m)로는 걸려야 한다 — 여기가 갈리면 못 나는 계획이 통과한다
  const pts = [okd(8000, 0, 200), okd(16000, 0, 495), okd(16000, 8000, 495)];
  const r = checkWaypoints(pts, 88, 0.7, 300, 0.04);
  const c = r.climbs.find((x) => x.idx === 1);
  // good[1]에서 90° 꺾이므로 lead = R ≈ 940 > 도달 반경 300
  assert.ok(Math.abs(c.ramp - (8000 - r.radius)) < 1, `ramp=${c.ramp} R=${r.radius}`);
  assert.equal(c.steep, true, `실제 경사 ${(c.grad * 100).toFixed(2)} %`);
  // 도달 반경만으로 쟀다면 7,700 m가 분모라 3.83 %로 통과했을 자리다
  assert.ok(295 / (8000 - 300) < 0.04, "이 배치는 옛 분모로는 통과한다 — 대조군");
});

test("checkWaypoints: 구간이 포획 반경보다 짧으면 계단이다 — 유한한 경사가 없다", () => {
  // 엔진 `_leg_alt`의 denom <= 0 분기 — 구간 시작에서 곧바로 목표 고도를 명령한다
  const pts = [okd(4000, 0, 200), okd(4200, 0, 260)];
  const r = checkWaypoints(pts, 88, 0.7, 300, 0.04);
  const c = r.climbs.find((x) => x.idx === 1);
  assert.equal(c.grad, Infinity);
  assert.equal(c.steep, true);
  assert.ok(r.warnings.some((w) => w.includes("계단")), r.warnings.join(" | "));
});

test("checkWaypoints: 한계를 인자로 덮어쓴다 — 기체가 바뀌면 판정선도 바뀐다", () => {
  const pts = [okd(4000, 0, 200), okd(14000, 0, 700)];   // 10 km에 500 m ≈ 5.2 %
  assert.equal(checkWaypoints(pts, 88, 0.7, 300, 0.04).climbs[0].steep, true);
  assert.equal(checkWaypoints(pts, 88, 0.7, 300, 0.11).climbs[0].steep, false);
});

test("checkWaypoints: tight 꺾임에서도 분모는 **잘린 예상 거리**를 뺀다 — 0이 아니다", () => {
  // 엔진 `_lead`는 min(lead, ½legIn, ½legOut)으로 자르지 끄지 않는다. 0으로 두면
  // 가장 급한 꺾임에서 분모를 가장 크게 낙관해 못 나는 구간이 조용히 통과한다 —
  // 미리보기가 그 꺾임에 호를 안 그리는 것과는 **다른 물음**이다
  const pts = [okd(1500, 0, 200), okd(3000, 0, 250), okd(3000, 1500, 250)];
  const r = checkWaypoints(pts, 88, 0.7, 100, 0.04);
  const c = r.climbs.find((x) => x.idx === 1);
  const corner = r.corners.find((x) => x.idx === 1);
  assert.equal(corner.tight, true, "이 배치의 꺾임은 tight여야 대조가 성립한다");
  // 잘린 예상 거리 = 구간 절반 = 750 m (도달 반경 100보다 크다)
  assert.ok(Math.abs(c.ramp - (1500 - corner.limit)) < 1e-9, `ramp=${c.ramp}`);
  assert.equal(c.steep, true, `grad=${(c.grad * 100).toFixed(2)} %`);
  // lead를 0으로 뒀다면 분모가 1,400 m라 3.57 %로 통과했을 자리다 — 대조군
  assert.ok(50 / (1500 - 100) < 0.04, "옛 계산으로는 통과한다");
});

// ── 한계를 **설정에서 유도한다** ────────────────────────────────────────────────
// 4 %는 기체의 수가 아니라 오토파일럿 `theta_hi`의 수다. 상수로 박으면 사용자가
// 그 값을 고쳐도 판정선이 안 따라온다 — 그 회귀를 막는 자리다.

test("climbGradientMax: 실측 세 점과 맞는다 — γ=(θ_hi−α)/(1+|k_hdot|·V)", () => {
  // 실측(engine 폐루프): theta_hi 0.3 → 3.56 % · 0.5 → 14.75 % · 0.7 → 14.52 %
  assert.ok(Math.abs(climbGradientMax(0.3, -0.008, 88) - 0.0356) < 0.001);
  // 0.5·0.7은 추력 천장에 잘린다 — 상한을 열어도 더 안 오른다는 사실이 이 단언이다
  assert.ok(Math.abs(climbGradientMax(0.5, -0.008, 88) - 0.147) < 0.005);
  assert.equal(climbGradientMax(0.7, -0.008, 88), climbGradientMax(0.5, -0.008, 88));
});

test("climbGradientMax: 피치 상한을 올리면 한계도 오른다 — 상수였다면 안 움직인다", () => {
  const lo = climbGradientMax(0.3, -0.008, 88);
  const hi = climbGradientMax(0.4, -0.008, 88);
  assert.ok(hi > lo * 2, `0.3→${lo} · 0.4→${hi} — 설정을 따라 움직여야 한다`);
});

test("climbGradientMax: 추력 천장을 넘지 않는다 — 열어도 안 오르는 자리가 있다", () => {
  // 이 천장이 없으면 "상한을 40°로 열면 경사 27 %"라는 거짓을 말한다(실측 14.5 %)
  for (const hi of [0.5, 0.7, 1.0, 1.4]) {
    assert.ok(climbGradientMax(hi, -0.008, 88) <= CLIMB_THRUST_CAP + 1e-9, `θ=${hi}`);
  }
});

test("climbGradientMax: 느리면 α가 커져 상승 여유가 줄어든다 — α ∝ 1/V²", () => {
  assert.ok(climbGradientMax(0.3, -0.008, 110) > climbGradientMax(0.3, -0.008, 88));
  // 실속 근처(71 m/s)에서는 순항 α가 상한을 먹어 올라갈 각이 남지 않는다
  assert.equal(climbGradientMax(0.3, -0.008, 72), 0);
});

test("climbGradientMax: 판정할 수 없는 입력은 null이지 0이 아니다", () => {
  // 0을 내면 **모든 상승이 급하다**고 나와 경고가 장식이 된다 — turnRadius와 같은 규약
  for (const a of [[NaN, -0.008, 88], [0.3, NaN, 88], [0.3, -0.008, 0], [0.3, -0.008, -1]]) {
    assert.equal(climbGradientMax(...a), null, JSON.stringify(a));
  }
});

test("checkWaypoints: 한계를 안 주면 세로를 판정하지 않는다 — 지어내지 않는다", () => {
  const pts = [okd(4000, 0, 200), okd(6000, 0, 600)]; // 20 % 요구 — 주면 걸린다
  assert.deepEqual(checkWaypoints(pts, 88, 0.7, 300).climbs, []);
  assert.deepEqual(checkWaypoints(pts, 88, 0.7, 300).warnings, []);
  assert.equal(checkWaypoints(pts, 88, 0.7, 300, 0.04).climbs[0].steep, true);
});

test("checkWaypoints: 추력 천장에 닿았으면 **상한을 열라고 말하지 않는다**", () => {
  const pts = [okd(4000, 0, 200), okd(6000, 0, 600)];
  const capped = checkWaypoints(pts, 88, 0.7, 300, CLIMB_THRUST_CAP);
  assert.ok(capped.warnings[0].includes("추력 한계"), capped.warnings[0]);
  assert.ok(!capped.warnings[0].includes("그 값을 올리면"), "열어도 소용없는데 열라고 한다");
  // 천장 아래면 반대로 설계변수를 짚어 준다 — 설계 툴에서 진짜 레버는 그쪽이다
  const room = checkWaypoints(pts, 88, 0.7, 300, 0.04);
  assert.ok(room.warnings[0].includes("theta_hi"), room.warnings[0]);
});

test("**뷰가 한계를 실제로 넘긴다** — 빠지면 경고만 조용히 사라진다", async () => {
  // 기본값이 없으므로 배선이 빠지면 세로 판정이 통째로 꺼지는데 화면은 멀쩡해 보인다.
  // v0.99의 getFlyable 원문 대조와 같은 부류다 — 스텁 테스트가 못 잡는 자리
  const src = await readFile(new URL("../views/sim.js", import.meta.url), "utf8");
  assert.match(src, /checkWaypoints\(pts, speed, bankMaxNow\(\), acceptRadiusOf\(\),\s*climbMaxNow\(speed\)\)/,
    "sim.js가 checkWaypoints에 climbMaxNow를 넘기지 않는다");
  assert.match(src, /climbGradientMax\(/, "sim.js가 climbGradientMax를 부르지 않는다");
});
