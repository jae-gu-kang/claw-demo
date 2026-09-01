/** lib/terrainpack.js — 지형 팩 파서·메시 테스트.

바이너리 포맷과 결측 정책이 이 파일의 대상이다. 특히 **결측을 메우지 않는다**는 규약은
눈으로 확인할 수 없다 — 0으로 채우면 없는 평지가, 이웃으로 채우면 없는 능선이 생기는데
둘 다 그럴듯해 보인다. 그래서 여기서 못박는다.
*/

import assert from "node:assert/strict";
import { test } from "node:test";

import {
  MAGIC, buildTerrainMesh, elevationAt, elevationAtIndex, parseTerrainPack, tierRect,
} from "./terrainpack.js";
import { nedToRender } from "./world3d.js";

const SCALE = 0.05, OFFSET = -100, NODATA = 65535;

/** 시험용 팩을 만든다 — 스크립트가 굽는 것과 같은 바이트 배치.
 *  `heights`는 [row][col] 표고(남→북, 서→동), null이면 결측. */
function makePack(tiers, origin = { lat_deg: 34.6, lon_deg: 127.2, h_ref: 0 }) {
  const metas = tiers.map((t) => ({
    name: t.name, n0: t.n0 ?? 0, e0: t.e0 ?? 0, step: t.step,
    rows: t.heights.length, cols: t.heights[0].length,
    encoding: "u16", scale: SCALE, offset: OFFSET, nodata: NODATA,
    coverage: 1, source: "테스트",
  }));
  const header = new TextEncoder().encode(JSON.stringify({ origin, tiers: metas }));
  const dataLen = metas.reduce((s, m) => s + m.rows * m.cols * 2, 0);
  const buf = new ArrayBuffer(12 + header.length + dataLen);
  const bytes = new Uint8Array(buf);
  const view = new DataView(buf);
  for (let i = 0; i < 8; i++) bytes[i] = MAGIC.charCodeAt(i);
  view.setUint32(8, header.length, true);
  bytes.set(header, 12);
  let off = 12 + header.length;
  for (const t of tiers) {
    for (const row of t.heights) {
      for (const z of row) {
        view.setUint16(off, z === null ? NODATA : Math.round((z - OFFSET) / SCALE), true);
        off += 2;
      }
    }
  }
  return buf;
}

const FLAT = [[10, 10, 10], [10, 10, 10], [10, 10, 10]];

/* ---------- 포맷 ---------- */

test("매직이 다르면 즉시 던진다 — 옛 팩을 새 코드로 조용히 읽지 않는다", () => {
  const buf = makePack([{ name: "t", step: 10, heights: FLAT }]);
  new Uint8Array(buf)[7] = "2".charCodeAt(0); // CLAWTER2
  assert.throws(() => parseTerrainPack(buf), /매직 불일치/);
});

test("데이터가 모자라면 던진다 — 잘린 팩을 절반만 읽지 않는다", () => {
  const buf = makePack([{ name: "t", step: 10, heights: FLAT }]);
  assert.throws(() => parseTerrainPack(buf.slice(0, buf.byteLength - 4)), /모자란다/);
});

test("너무 짧은 입력도 던진다", () => {
  assert.throws(() => parseTerrainPack(new ArrayBuffer(4)), /짧다/);
});

test("왕복 — 구운 표고가 그대로 읽힌다 (양자화 오차 ±2.5 cm 안)", () => {
  const heights = [[0, 12.5, 300], [-50, 7.77, 1000], [42, 0, 3000]];
  const { origin, tiers } = parseTerrainPack(makePack([{ name: "t", step: 10, heights }]));
  assert.equal(origin.lat_deg, 34.6);
  assert.equal(tiers.length, 1);
  for (let r = 0; r < 3; r++) {
    for (let c = 0; c < 3; c++) {
      const got = elevationAtIndex(tiers[0], r, c);
      assert.ok(Math.abs(got - heights[r][c]) <= SCALE / 2 + 1e-9,
        `(${r},${c}) ${got} vs ${heights[r][c]}`);
    }
  }
});

test("티어가 여럿이면 헤더 순서대로 데이터가 붙는다", () => {
  const { tiers } = parseTerrainPack(makePack([
    { name: "core", step: 10, heights: [[1, 2], [3, 4]] },
    { name: "outer", step: 30, heights: [[50, 60], [70, 80]] },
  ]));
  assert.deepEqual(tiers.map((t) => t.name), ["core", "outer"]);
  assert.ok(Math.abs(elevationAtIndex(tiers[0], 0, 0) - 1) < 0.03);
  assert.ok(Math.abs(elevationAtIndex(tiers[1], 1, 1) - 80) < 0.03);
});

/* ---------- 결측 (메우지 않는다) ---------- */

test("결측은 null이다 — 0도 이웃 값도 아니다", () => {
  const { tiers } = parseTerrainPack(makePack([
    { name: "t", step: 10, heights: [[10, null, 10], [10, 10, 10], [10, 10, 10]] },
  ]));
  assert.equal(elevationAtIndex(tiers[0], 0, 1), null);
  assert.ok(Math.abs(elevationAtIndex(tiers[0], 0, 0) - 10) < 0.03);
});

test("격자 밖 인덱스도 null이다 (조용히 가장자리 값을 되풀이하지 않는다)", () => {
  const { tiers } = parseTerrainPack(makePack([{ name: "t", step: 10, heights: FLAT }]));
  for (const [r, c] of [[-1, 0], [0, -1], [3, 0], [0, 3]]) {
    assert.equal(elevationAtIndex(tiers[0], r, c), null, `(${r},${c})`);
  }
});

test("이웃이 하나라도 결측이면 보간값도 null이다", () => {
  // 4×4로 잡는다 — 3×3에서 가운데가 비면 **모든 내부 셀이 그 구멍에 닿아**
  // "떨어진 자리"가 존재하지 않는다(첫 시도가 그래서 빨갰다).
  const { tiers } = parseTerrainPack(makePack([
    { name: "t", step: 10, heights: [
      [10, 10, 10, 10], [10, null, 10, 10], [10, 10, 10, 10], [10, 10, 10, 10]] },
  ]));
  assert.equal(elevationAt(tiers[0], 15, 15), null, "결측 셀에 걸친 자리");
  assert.equal(elevationAt(tiers[0], 5, 5), null, "그 셀의 반대쪽 귀퉁이도 마찬가지");
  const far = elevationAt(tiers[0], 25, 25); // (2,2)~(3,3) 셀 — 구멍과 닿지 않는다
  assert.ok(far !== null && Math.abs(far - 10) < 0.03, `떨어진 자리는 정상: ${far}`);
});

/* ---------- 보간 ---------- */

test("경사면에서 이중선형은 정확하다 (평면은 이중선형으로 완전히 표현된다)", () => {
  // z = 0.5*n + 0.2*e + 10  — 격자 간격 10 m
  const heights = [];
  for (let r = 0; r < 4; r++) {
    heights.push([...Array(4)].map((_, c) => 0.5 * (r * 10) + 0.2 * (c * 10) + 10));
  }
  const { tiers } = parseTerrainPack(makePack([{ name: "t", step: 10, heights }]));
  for (const [n, e] of [[0, 0], [5, 5], [12.5, 27.5], [30, 30]]) {
    const want = 0.5 * n + 0.2 * e + 10;
    const got = elevationAt(tiers[0], n, e);
    assert.ok(Math.abs(got - want) < 0.05, `(${n},${e}) ${got} vs ${want}`);
  }
});

test("격자 원점 n0·e0가 반영된다", () => {
  const { tiers } = parseTerrainPack(makePack([
    { name: "t", step: 10, n0: -1000, e0: -1000, heights: [[5, 5], [5, 5]] },
  ]));
  assert.ok(Math.abs(elevationAt(tiers[0], -1000, -1000) - 5) < 0.03);
  assert.equal(elevationAt(tiers[0], 0, 0), null, "격자 밖");
  assert.deepEqual(tierRect(tiers[0]), { n0: -1000, e0: -1000, n1: -990, e1: -990 });
});

/* ---------- 메시 ---------- */

test("평지 메시는 셀마다 삼각형 2개이고 법선이 곧게 위를 본다", () => {
  const { tiers } = parseTerrainPack(makePack([{ name: "t", step: 10, heights: FLAT }]));
  const m = buildTerrainMesh(tiers[0]);
  assert.equal(m.triangles, 2 * 2 * 2, "2×2 셀 × 2");
  for (let i = 0; i < m.normals.length; i += 3) {
    assert.ok(Math.abs(m.normals[i]) < 1e-9 && Math.abs(m.normals[i + 1]) < 1e-9);
    assert.ok(Math.abs(m.normals[i + 2] + 1) < 1e-9, "D축 음수 = 위");
  }
});

test("결측 셀은 삼각형을 만들지 않는다 — 구멍으로 남는다", () => {
  const { tiers } = parseTerrainPack(makePack([
    { name: "t", step: 10, heights: [[10, 10, 10], [10, null, 10], [10, 10, 10]] },
  ]));
  const m = buildTerrainMesh(tiers[0]);
  // 가운데가 빠지면 그것을 꼭짓점으로 쓰는 네 셀이 전부 사라진다
  assert.equal(m.triangles, 0);
  assert.equal(m.skippedCells, 4);
});

test("경사면 법선이 오르막 반대쪽으로 기운다", () => {
  // 북으로 갈수록 높아지는 면 → 법선의 N 성분이 음수여야 한다
  const heights = [[0, 0], [10, 10]];
  const { tiers } = parseTerrainPack(makePack([{ name: "t", step: 10, heights }]));
  const m = buildTerrainMesh(tiers[0]);
  assert.ok(m.normals[0] < 0, `법선 N 성분 ${m.normals[0]}`);
  assert.ok(Math.abs(m.normals[1]) < 1e-9, "동서로는 평평");
});

test("정점 위치는 NED이고 결측 자리는 NaN이다 (0이 아니다)", () => {
  const { tiers } = parseTerrainPack(makePack([
    { name: "t", step: 10, n0: 100, e0: 200, heights: [[7, null], [7, 7]] },
  ]));
  const m = buildTerrainMesh(tiers[0]);
  assert.equal(m.positions[0], 100, "n0");
  assert.equal(m.positions[1], 200, "e0");
  assert.ok(Math.abs(m.positions[2] + 7) < 0.03, "D = −표고");
  assert.ok(Number.isNaN(m.positions[5]), "결측 자리는 NaN");
});

test("skipRect 안쪽 셀은 건너뛴다 — 티어가 겹쳐 z-fighting을 내지 않게", () => {
  const heights = [...Array(5)].map(() => Array(5).fill(10));
  const { tiers } = parseTerrainPack(makePack([{ name: "t", step: 10, n0: 0, e0: 0, heights }]));
  const all = buildTerrainMesh(tiers[0]);
  const holed = buildTerrainMesh(tiers[0], { skipRect: { n0: 10, e0: 10, n1: 30, e1: 30 } });
  assert.ok(holed.triangles < all.triangles);
  assert.ok(holed.skippedCells > 0);
  // 경계 셀은 남아야 안쪽 티어와의 사이에 틈이 생기지 않는다
  assert.ok(holed.triangles > 0, "전부 지워 버리면 안 된다");
});

test("stride로 솎으면 정점이 줄고 간격이 늘어난다", () => {
  const heights = [...Array(5)].map((_, r) => Array(5).fill(r));
  const { tiers } = parseTerrainPack(makePack([{ name: "t", step: 10, heights }]));
  const m = buildTerrainMesh(tiers[0], { stride: 2 });
  assert.equal(m.rows, 3);
  assert.equal(m.cols, 3);
  assert.equal(m.step, 20);
});

test("정점이 65,535를 넘으면 Uint32 인덱스를 쓴다 — 조용히 잘리지 않게", () => {
  const big = [...Array(300)].map(() => Array(300).fill(5));
  const { tiers } = parseTerrainPack(makePack([{ name: "t", step: 10, heights: big }]));
  const m = buildTerrainMesh(tiers[0]);
  assert.ok(m.indices instanceof Uint32Array, "90,000 정점");
  const small = parseTerrainPack(makePack([{ name: "t", step: 10, heights: FLAT }])).tiers[0];
  assert.ok(buildTerrainMesh(small).indices instanceof Uint16Array);
});

test("삼각형 감김이 위를 향한다 — 뒤집히면 위에서 지형 밑면을 보게 된다", () => {
  // 렌더러 축 x=e, y=−d, z=−n에서 앞면 법선이 +y(위)여야 한다. 라이브에서 화면 아래
  // 절반이 새까맣게 나와 잡은 회귀다 — 조명이 위에 있으니 밑면은 검게 보인다.
  const { tiers } = parseTerrainPack(makePack([{ name: "t", step: 10, heights: FLAT }]));
  const m = buildTerrainMesh(tiers[0]);
  // **어댑터와 같은 사상을 읽는다** — 여기서 다시 적으면 어댑터가 바뀌어도 이 테스트는
  // 옛 사상 기준으로 계속 통과한다(리뷰 지적).
  const toWorld = (i) => nedToRender(m.positions[3 * i], m.positions[3 * i + 1],
                                     m.positions[3 * i + 2]);
  assert.ok(m.indices.length >= 3);
  for (let k = 0; k < m.indices.length; k += 3) {
    const [A, B, C] = [toWorld(m.indices[k]), toWorld(m.indices[k + 1]), toWorld(m.indices[k + 2])];
    const u = [B[0] - A[0], B[1] - A[1], B[2] - A[2]];
    const v = [C[0] - A[0], C[1] - A[1], C[2] - A[2]];
    const ny = u[2] * v[0] - u[0] * v[2]; // (u × v)의 y 성분
    assert.ok(ny > 0, `삼각형 ${k / 3}의 앞면이 아래를 본다 (y=${ny})`);
  }
});

test("stride가 격자를 나누어떨어지지 않아도 마지막 행·열이 빠지지 않는다", () => {
  // 단순히 stride로만 세면 6행 격자에 stride 2를 주었을 때 인덱스 0·2·4만 잡히고
  // 마지막 행(5)이 빠져 **티어 경계에 띠가 생긴다** — 격자는 tierRect까지 덮는다고
  // 되어 있는데 메시는 못 미치는 상태다. 오늘 stride를 쓰는 곳은 없지만 함정은 남는다.
  const heights = [...Array(6)].map(() => Array(6).fill(10));
  const { tiers } = parseTerrainPack(makePack([{ name: "t", step: 10, heights }]));
  const rect = tierRect(tiers[0]);
  const m = buildTerrainMesh(tiers[0], { stride: 2 });
  let maxN = -Infinity, maxE = -Infinity;
  for (let i = 0; i < m.positions.length; i += 3) {
    maxN = Math.max(maxN, m.positions[i]);
    maxE = Math.max(maxE, m.positions[i + 1]);
  }
  assert.equal(maxN, rect.n1, "북쪽 끝까지 덮어야 한다");
  assert.equal(maxE, rect.e1, "동쪽 끝까지 덮어야 한다");
});

test("가장자리 간격이 짧아져도 기울기가 정확하다 — 값을 못박는다", () => {
  // 마지막 칸은 stride보다 짧다. 고정 간격으로 나누면 그 두 줄의 기울기가 0.375·0.250으로
  // 무너지는데(참값 0.5), **길이와 부호만 보면 그 변이가 살아남는다**(리뷰 변이시험).
  // 법선이 (−dz/dn, −dz/de, −1)/‖·‖ 이므로 normals[i]/normals[i+2]가 곧 dz/dn이다.
  const heights = [...Array(6)].map((_, r) => Array(6).fill(r * 5)); // 북으로 0.5 경사
  const { tiers } = parseTerrainPack(makePack([{ name: "t", step: 10, heights }]));
  const m = buildTerrainMesh(tiers[0], { stride: 2 });
  for (let k = 0; k < m.rows * m.cols; k++) {
    const i = 3 * k;
    const len = Math.hypot(m.normals[i], m.normals[i + 1], m.normals[i + 2]);
    assert.ok(Math.abs(len - 1) < 1e-6, `법선 길이 ${len}`);
    const dzdn = m.normals[i] / m.normals[i + 2];
    assert.ok(Math.abs(dzdn - 0.5) < 1e-6,
      `정점 ${k} (행 ${Math.floor(k / m.cols)}) 기울기 ${dzdn} — 참값 0.5`);
    assert.ok(Math.abs(m.normals[i + 1] / m.normals[i + 2]) < 1e-9, "동서로는 평평");
  }
});

test("skipRect가 안쪽 셀을 정확히 그만큼만 지운다 (개수를 못박는다)", () => {
  // "겹친 삼각형이 줄었다"만 보면 상한 판정을 지운 변이도 통과한다 — 그 변이는 안쪽
  // 사각형의 북동쪽 사분면을 통째로 지운다(리뷰 변이시험). 정답 수를 적는다.
  const heights = [...Array(5)].map(() => Array(5).fill(10));
  const { tiers } = parseTerrainPack(makePack([{ name: "t", step: 10, n0: 0, e0: 0, heights }]));
  const all = buildTerrainMesh(tiers[0]);
  assert.equal(all.triangles, 4 * 4 * 2, "5×5 격자 = 4×4 셀");
  const holed = buildTerrainMesh(tiers[0], { skipRect: { n0: 10, e0: 10, n1: 30, e1: 30 } });
  // 셀 (r,c)가 안에 들려면 r*10 ≥ 10 이고 (r+1)*10 ≤ 30 → r ∈ {1,2}. 열도 같아 2×2 = 4칸
  assert.equal(holed.skippedCells, 4);
  assert.equal(holed.triangles, (16 - 4) * 2);
});

test("stride와 skipRect를 함께 줘도 판정이 실제 좌표를 따른다", () => {
  // cellInside가 실제 정점 좌표를 본다는 주장의 테스트 — 간격이 stride만큼 벌어지면
  // 같은 사각형이 지우는 칸 수도 달라진다.
  const heights = [...Array(9)].map(() => Array(9).fill(10));
  const { tiers } = parseTerrainPack(makePack([{ name: "t", step: 10, n0: 0, e0: 0, heights }]));
  const m = buildTerrainMesh(tiers[0], { stride: 2, skipRect: { n0: 20, e0: 20, n1: 60, e1: 60 } });
  // stride 2 → 정점 n = 0,20,40,60,80. 셀 (r,c)가 안에 들려면 n0 ≥ 20 이고 n1 ≤ 60 → r ∈ {1,2}
  assert.equal(m.skippedCells, 4);
  assert.ok(m.triangles > 0);
});
