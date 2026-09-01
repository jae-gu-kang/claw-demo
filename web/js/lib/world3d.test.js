/** lib/world3d.js — 3D 월드 수치 계층 테스트.

이 파일이 존재하는 이유가 첫 두 테스트다. 결측 정책이 뷰에 흩어져 있을 때 궤적 선은
끊으면서 기체 위치는 0으로 메워, 결측 프레임에서 기체가 NED 원점으로 순간이동하고
후방차분 속도가 수만 m/s로 튀었다. 같은 물음의 답을 한곳에 모으고 여기서 못박는다.
*/

import assert from "node:assert/strict";
import { test } from "node:test";

import {
  attitudeAt, niceStep, originsAgree, sampleAt, sceneExtent, trackPoints, velocityAt,
} from "./world3d.js";

/** 결측이 섞인 신호 — 직렬화가 비유한값을 null로 바꾼 모양 (M13 serialize). */
const GAPPY = {
  pn: [100, 200, null, 400],
  pe: [10, 20, 30, 40],
  h: [50, 60, 70, 80],
};

/* ---------- 결측 (이 층이 존재하는 이유) ---------- */

test("결측 표본은 null이다 — 0으로 메우지 않는다", () => {
  assert.deepEqual(sampleAt(GAPPY, 0), [100, 10, -50]);
  assert.equal(sampleAt(GAPPY, 2), null);
  // 셋 중 어느 하나만 빠져도 표본 전체가 결측이다
  assert.equal(sampleAt({ pn: [1], pe: [null], h: [3] }, 0), null);
  assert.equal(sampleAt({ pn: [1], pe: [2], h: [NaN] }, 0), null);
  assert.equal(sampleAt({ pn: [1], pe: [2] }, 0), null, "신호 자체가 없는 경우");
});

test("고도 h는 상방 +이고 D는 하방 + — 부호가 뒤집힌다", () => {
  assert.equal(sampleAt({ pn: [0], pe: [0], h: [300] }, 0)[2], -300);
});

test("궤적의 결측 자리는 NaN이다 — 0이면 원점에서 뻗는 가짜 선분이 된다", () => {
  const { points, breaks } = trackPoints(GAPPY, 4);
  assert.deepEqual(breaks, [2]);
  assert.ok(Number.isNaN(points[6]) && Number.isNaN(points[7]) && Number.isNaN(points[8]));
  // 성한 표본은 그대로
  assert.equal(points[0], 100);
  assert.equal(points[9], 400);
});

test("결측 인덱스가 breaks에 빠짐없이 들어간다 (양 끝·연속 결측 포함)", () => {
  const s = { pn: [null, 1, null, null, 4], pe: [0, 1, 2, 3, 4], h: [0, 1, 2, 3, 4] };
  assert.deepEqual(trackPoints(s, 5).breaks, [0, 2, 3]);
});

test("**나가는 구간도 끊긴다** — 소비자가 양 끝을 다 봐야 한다는 계약", () => {
  // 리뷰가 재현한 결함: 들어오는 구간만 끊으면 (결측 → 다음 점) 선분이 살아남고,
  // 그 자리가 0이면 원점에서 뻗어 나오는 그럴듯한 선이 그려진다.
  const { points, breaks } = trackPoints(GAPPY, 4);
  const cut = new Set(breaks);
  const drawn = [];
  for (let i = 0; i + 5 < points.length; i += 3) {
    const a = i / 3, b = a + 1;
    if (cut.has(a) || cut.has(b)) continue; // ← 이 계약대로면
    drawn.push([a, b]);
  }
  assert.deepEqual(drawn, [[0, 1]], "결측 2를 양쪽에서 끊으면 구간 하나만 남는다");
  // 한쪽만 보는 옛 로직이면 [2,3]이 살아남고 그 시작점이 NaN이다 — 그것을 증명한다
  const naive = [];
  for (let i = 0; i + 5 < points.length; i += 3) {
    if (cut.has(i / 3 + 1)) continue;
    naive.push([i / 3, i / 3 + 1]);
  }
  assert.deepEqual(naive, [[0, 1], [2, 3]]);
  assert.ok(Number.isNaN(points[6]), "그 살아남은 구간의 시작점은 결측 자리다");
});

/* ---------- 속도 ---------- */

test("후방차분 속도는 성한 두 표본 사이에서만 나온다", () => {
  const t = [0, 0.1, 0.2, 0.3];
  assert.deepEqual(velocityAt(t, GAPPY, 1), [1000, 100, -100]);
  assert.equal(velocityAt(t, GAPPY, 0), null, "첫 표본은 앞이 없다");
  assert.equal(velocityAt(t, GAPPY, 2), null, "자신이 결측");
  assert.equal(velocityAt(t, GAPPY, 3), null, "앞이 결측 — 도약을 dt로 나누지 않는다");
});

test("dt가 0 이하면 속도를 내지 않는다 (0으로 나누기·시간 역행)", () => {
  const s = { pn: [0, 100], pe: [0, 0], h: [0, 0] };
  assert.equal(velocityAt([0, 0], s, 1), null);
  assert.equal(velocityAt([1, 0], s, 1), null);
});

/* ---------- 기준면 ---------- */

test("기준면은 궤적 수평 범위의 2.5배이고 하한이 있다", () => {
  assert.equal(sceneExtent({ pn: [0, 10000], pe: [0, 0] }), 25000);
  assert.equal(sceneExtent({ pn: [0, 1], pe: [0, 1] }), 2000, "작은 궤적도 최소 2 km");
});

test("기준면 계산이 결측을 건너뛴다 — 0이 범위에 끼어들지 않는다", () => {
  // pn이 전부 5000 근처인데 결측을 0으로 세면 범위가 5000까지 벌어진다
  const s = { pn: [5000, null, 5100], pe: [5000, null, 5100] };
  assert.equal(sceneExtent(s), 2000, "실제 범위 100 m → 하한 적용");
});

test("표본이 하나도 성하지 않으면 기본값을 낸다", () => {
  assert.equal(sceneExtent({ pn: [null, null], pe: [null, null] }), 4000);
  assert.equal(sceneExtent({}), 4000);
});

test("격자 간격은 1·2·5 계열이다", () => {
  for (const [extent, want] of [[25000, 2000], [2000, 100], [4000, 200], [500, 50]]) {
    assert.equal(niceStep(extent), want, `extent ${extent}`);
  }
});

/* ---------- 원점 정합 (지형을 겹쳐 그려도 되는가) ---------- */

const PACK_ORIGIN = { lat_deg: 34.6, lon_deg: 127.2, h_ref: 0 };

test("같은 원점이면 겹쳐 그릴 수 있다", () => {
  const r = originsAgree(PACK_ORIGIN, { lat: 34.6, lon: 127.2 });
  assert.equal(r.ok, true);
  assert.equal(r.reason, null);
});

test("결과에 원점이 없으면 지형을 얹지 않는다 — 이것이 기본 경로였다", () => {
  // SimRunIn.origin은 선택이라 원점 없는 결과가 흔하다. 그때 지형을 그대로 깔면
  // 화면이 "위치를 말할 수 없다"고 쓰면서 동시에 특정 지역 지형을 기체 밑에 그린다.
  const r = originsAgree(PACK_ORIGIN, null);
  assert.equal(r.ok, false);
  assert.ok(r.reason.includes("원점이 없어"));
});

test("원점이 다르면 사유에 두 좌표를 다 적는다", () => {
  const r = originsAgree(PACK_ORIGIN, { lat: 37.5, lon: 127.0 });
  assert.equal(r.ok, false);
  assert.ok(r.reason.includes("34.6000") && r.reason.includes("37.5000"), r.reason);
});

test("허용오차 안의 차이는 같은 원점으로 본다", () => {
  assert.equal(originsAgree(PACK_ORIGIN, { lat: 34.6 + 5e-7, lon: 127.2 }).ok, true);
  assert.equal(originsAgree(PACK_ORIGIN, { lat: 34.6 + 5e-5, lon: 127.2 }).ok, false);
});

test("팩에 원점이 없어도 거부한다", () => {
  assert.equal(originsAgree(null, { lat: 34.6, lon: 127.2 }).ok, false);
});

/* ---------- 자세 표본 (위치와 같은 규약) ---------- */

const ATT = { phi: [0.1, null, 0.3], theta: [0.2, 0.2, 0.2], psi: [0.3, 0.3, 0.3] };

test("자세 표본은 셋이 다 성해야 값을 낸다 — 하나라도 결측이면 null", () => {
  // `?? 0`으로 메우면 없는 수평비행을 지어내고, 그 쿼터니언이 온보드 시점을 몬다.
  // 이 테스트가 없어서 구현을 옛 `?? 0` 모양으로 되돌려도 전부 초록이었다(리뷰 변이시험).
  assert.deepEqual(attitudeAt(ATT, 0), [0.1, 0.2, 0.3]);
  assert.equal(attitudeAt(ATT, 1), null, "φ 결측");
  assert.equal(attitudeAt({ phi: [0], theta: [null], psi: [0] }, 0), null, "θ 결측");
  assert.equal(attitudeAt({ phi: [0], theta: [0], psi: [null] }, 0), null, "ψ 결측");
});

test("자세 신호 자체가 없는 결과도 null이다 (0으로 메우지 않는다)", () => {
  assert.equal(attitudeAt({}, 0), null);
  assert.equal(attitudeAt({ phi: [0.1] }, 0), null, "θ·ψ 신호 부재");
  assert.equal(attitudeAt({ phi: [NaN], theta: [0], psi: [0] }, 0), null, "NaN");
});

test("자세 0은 결측이 아니다 — 수평비행은 유효한 값이다", () => {
  assert.deepEqual(attitudeAt({ phi: [0], theta: [0], psi: [0] }, 0), [0, 0, 0]);
});
