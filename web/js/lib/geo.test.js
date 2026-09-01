/** lib/geo.js — 측지 좌표 계층 테스트.

핵심은 둘이다. ① `data/geodesy-fixture.json`을 **엔진 테스트와 같이 읽어** 두 구현이 갈라진
것을 잡는다(engine/claw/tests/test_env_geodesy.py가 같은 파일을 본다). ② 메르카토르
투영 미터와 지상 미터를 혼동하는 21.5% 오차를 못박는다.
*/

import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { test } from "node:test";
import { fileURLToPath } from "node:url";

import {
  DEG2RAD, RAD2DEG, WEB_MERCATOR,
  geodeticToNed, groundMetersPerPixel, localScales, mercatorScaleFactor,
  nedToGeodetic, radiusMeridian, radiusPrimeVertical,
  tileBoundsGeodetic, tileOf, zoomForScale,
} from "./geo.js";

const HERE = dirname(fileURLToPath(import.meta.url));
const FIXTURE = JSON.parse(
  readFileSync(join(HERE, "..", "..", "..", "data", "geodesy-fixture.json"), "utf8"),
);

const LAT0 = 34.6 * DEG2RAD;
const LON0 = 127.2 * DEG2RAD;
const ORIGIN = { latRad: LAT0, lonRad: LON0 };

/* ---------- 왕복 항등 ---------- */

test("nedToGeodetic ↔ geodeticToNed는 정확한 역함수다", () => {
  for (const [n, e] of [[0, 0], [1000, 0], [0, 1000], [-20000, 20000], [12345.6, -7890.1]]) {
    const g = nedToGeodetic(n, e, ORIGIN);
    const back = geodeticToNed(g.latRad, g.lonRad, ORIGIN);
    assert.ok(Math.abs(back.n - n) < 1e-9, `n ${back.n} != ${n}`);
    assert.ok(Math.abs(back.e - e) < 1e-9, `e ${back.e} != ${e}`);
  }
});

/* ---------- 스케일의 정체 (M과 N을 혼동하지 않는가) ---------- */

test("북쪽 이동은 M(φ)로만 나뉘고 경도를 바꾸지 않는다", () => {
  const g = nedToGeodetic(1000, 0, ORIGIN);
  assert.ok(Math.abs(g.latRad - LAT0 - 1000 / radiusMeridian(LAT0)) < 1e-15);
  assert.equal(g.lonRad, LON0);
});

test("동쪽 이동은 N(φ)·cos φ로 나뉘고 위도를 바꾸지 않는다", () => {
  const g = nedToGeodetic(0, 1000, ORIGIN);
  const expected = 1000 / (radiusPrimeVertical(LAT0) * Math.cos(LAT0));
  assert.ok(Math.abs(g.lonRad - LON0 - expected) < 1e-15);
  assert.equal(g.latRad, LAT0);
});

test("중위도에서 동서 스케일이 남북보다 작다 (자오선이 극으로 모인다)", () => {
  const s = localScales(LAT0);
  assert.ok(s.east < s.north);
  assert.ok(Math.abs(s.east / s.north - 0.8269) < 1e-4);
});

test("극 근방 원점과 비유한값은 조용히 발산하지 않고 던진다", () => {
  assert.throws(() => localScales(89.5 * DEG2RAD), /접평면/);
  assert.throws(() => localScales(-89.5 * DEG2RAD), /접평면/);
  assert.throws(() => localScales(NaN));
  assert.throws(() => localScales(LAT0, Infinity));
});

/* ---------- 엔진과의 공유 고정점 ---------- */

test("공유 고정점이 이 구현과 일치한다 (엔진 test_env_geodesy.py와 같은 파일)", () => {
  const o = FIXTURE.origin;
  const tol = FIXTURE._tolerance_m;
  for (const blk of FIXTURE.blocks) {
    const origin = { latRad: o.lat_deg * DEG2RAD, lonRad: o.lon_deg * DEG2RAD, hRef: blk.h_ref };
    const s = localScales(origin.latRad, origin.hRef);
    // 스케일이 같다는 것은 곧 WGS-84 상수가 엔진과 같다는 뜻이다 (별도 대조가 필요 없다)
    assert.ok(Math.abs(s.north / blk.local_scales.north_m_per_rad - 1) < 1e-12,
      `h_ref=${blk.h_ref} 북 스케일`);
    assert.ok(Math.abs(s.east / blk.local_scales.east_m_per_rad - 1) < 1e-12,
      `h_ref=${blk.h_ref} 동 스케일`);
    for (const c of blk.cases) {
      const g = nedToGeodetic(c.n, c.e, origin);
      // 각도 오차를 미터로 환산해 비교한다 — 허용오차가 거리 단위여야 뜻이 있다
      const dN = (g.latRad - c.lat_deg * DEG2RAD) * s.north;
      const dE = (g.lonRad - c.lon_deg * DEG2RAD) * s.east;
      assert.ok(Math.abs(dN) < tol, `h_ref=${blk.h_ref} n=${c.n} 북 오차 ${dN} m`);
      assert.ok(Math.abs(dE) < tol, `h_ref=${blk.h_ref} e=${c.e} 동 오차 ${dE} m`);
    }
  }
});

test("고정점이 h_ref를 실제로 묶는다 — hRef를 무시하는 구현은 통과하지 못한다", () => {
  // 0인 블록만 있으면 `+ hRef`를 지워도 전부 통과한다(리뷰의 변이시험). 서버는 h_ref로
  // 활주로 표고를 보내므로 죽은 인자가 아니다 — 블록마다 수가 달라야 그 구멍이 막힌다.
  assert.ok(FIXTURE.blocks.some((b) => b.h_ref !== 0));
  const norths = new Set(FIXTURE.blocks.map((b) => b.local_scales.north_m_per_rad));
  assert.equal(norths.size, FIXTURE.blocks.length, "블록마다 스케일이 달라야 한다");
  // 그리고 이 구현이 실제로 h_ref만큼 스케일을 키우는지 (엔진 test와 같은 단언)
  const lo = localScales(LAT0, 0);
  const hi = localScales(LAT0, 1000);
  assert.ok(Math.abs(hi.north - lo.north - 1000) < 1e-6);
  assert.ok(Math.abs(hi.east - lo.east - 1000 * Math.cos(LAT0)) < 1e-6);
});

/* ---------- 메르카토르: 투영 미터 ≠ 지상 미터 ---------- */

test("메르카토르 스케일 계수는 위도 34.6°에서 1.2149다", () => {
  assert.ok(Math.abs(mercatorScaleFactor(LAT0) - 1.21487) < 1e-4);
});

test("지상 해상도는 투영 해상도에 cos φ를 곱한 것이다 (21.5% 오차의 근원)", () => {
  const z = 13;
  const projected = WEB_MERCATOR.resolutionAt(z);
  const ground = groundMetersPerPixel(WEB_MERCATOR, LAT0, z);
  assert.ok(Math.abs(ground / projected - Math.cos(LAT0)) < 1e-12);
  // 혼동하면 21.5% 어긋난다 — 그 크기를 수치로 남긴다
  assert.ok(Math.abs(projected / ground - 1.21487) < 1e-4);
});

test("적도 z=0 지상 해상도는 156543.034 m/px이고 줌마다 정확히 절반이 된다", () => {
  assert.ok(Math.abs(groundMetersPerPixel(WEB_MERCATOR, 0, 0) - 156543.03392804097) < 1e-6);
  for (const z of [0, 5, 13, 18]) {
    const a = groundMetersPerPixel(WEB_MERCATOR, LAT0, z);
    const b = groundMetersPerPixel(WEB_MERCATOR, LAT0, z + 1);
    assert.ok(Math.abs(a / b - 2) < 1e-12, `z=${z}`);
  }
});

/* ---------- 타일 좌표 ---------- */

test("z=0은 타일이 하나뿐이고, 적도·본초자오선은 z=2에서 (2,2)다", () => {
  assert.deepEqual({ x: 0, y: 0 }, pick(tileOf(WEB_MERCATOR, LAT0, LON0, 0)));
  assert.deepEqual({ x: 2, y: 2 }, pick(tileOf(WEB_MERCATOR, 0, 0, 2)));
});

test("경도 ±180°는 존재하지 않는 타일 대신 양 끝 타일로 클램프된다", () => {
  assert.equal(tileOf(WEB_MERCATOR, 0, Math.PI, 3).x, 7, "2^3 - 1");
  // 아래쪽을 안 막으면 음수 타일 x가 나가고 그 URL은 조용히 404가 된다
  assert.equal(tileOf(WEB_MERCATOR, 0, -Math.PI, 3).x, 0);
  for (const z of [0, 5, 13]) {
    for (const lon of [-Math.PI, Math.PI, -Math.PI + 1e-15, Math.PI - 1e-15]) {
      const t = tileOf(WEB_MERCATOR, 0, lon, z);
      assert.ok(t.x >= 0 && t.x < 2 ** z, `z=${z} lon=${lon} → x=${t.x}`);
    }
  }
});

test("메르카토르 한계 밖 위도는 Infinity가 아니라 null이다", () => {
  assert.equal(tileOf(WEB_MERCATOR, 86 * DEG2RAD, LON0, 5), null);
  assert.equal(tileOf(WEB_MERCATOR, -86 * DEG2RAD, LON0, 5), null);
  assert.equal(tileOf(WEB_MERCATOR, NaN, LON0, 5), null);
});

test("타일 경계는 그 타일 안의 점을 되돌려 준다 (forward/inverse 정합)", () => {
  const z = 13;
  const t = tileOf(WEB_MERCATOR, LAT0, LON0, z);
  const b = tileBoundsGeodetic(WEB_MERCATOR, z, t.x, t.y);
  assert.ok(b.west <= LON0 && LON0 < b.east, "경도가 타일 안");
  assert.ok(b.south < LAT0 && LAT0 <= b.north, "위도가 타일 안");
  // 북쪽 경계가 남쪽보다 위 — v가 아래로 증가하는 규약을 뒤집지 않았는가
  assert.ok(b.north > b.south);
});

/* ---------- 줌 선택 ---------- */

test("zoomForScale은 축척에 맞는 줌을 고르고, dpr 2는 한 단계 더 높인다", () => {
  const mPerPx = 2.0; // 논리 픽셀당 지상 2 m
  const z1 = zoomForScale(WEB_MERCATOR, mPerPx, LAT0, { dpr: 1 });
  const z2 = zoomForScale(WEB_MERCATOR, mPerPx, LAT0, { dpr: 2 });
  assert.equal(z2, z1 + 1);
  // 고른 줌의 지상 해상도가 목표 축척과 2배 안쪽에서 맞는가
  const got = groundMetersPerPixel(WEB_MERCATOR, LAT0, z1);
  assert.ok(got > mPerPx / 2 && got < mPerPx * 2, `${got} vs ${mPerPx}`);
});

test("zoomForScale은 zMin·zMax로 클램프되고 비양수 축척을 거부한다", () => {
  assert.equal(zoomForScale(WEB_MERCATOR, 1e-6, LAT0, { zMax: 18 }), 18);
  assert.equal(zoomForScale(WEB_MERCATOR, 1e9, LAT0, { zMin: 3 }), 3);
  assert.throws(() => zoomForScale(WEB_MERCATOR, 0, LAT0));
  assert.throws(() => zoomForScale(WEB_MERCATOR, -1, LAT0));
});

test("환산 상수는 서로의 역수다", () => {
  assert.ok(Math.abs(DEG2RAD * RAD2DEG - 1) < 1e-15);
});

function pick(t) {
  return { x: t.x, y: t.y };
}
